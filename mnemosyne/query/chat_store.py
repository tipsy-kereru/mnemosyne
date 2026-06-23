"""SPEC-NLQUERY-001 REQ-NL-006: append-only chat session persistence.

``ChatStore`` creates / appends / lists / archives chat sessions on the
shared KnowledgeGraph connection. No ``DELETE`` or row-removing ``UPDATE`` is
ever issued against ``chat_turns``; archiving flips ``chat_sessions.status``
to ``'archived'`` (tombstone) per the SPEC-MCP-001 no-delete contract.

DDL is additive + idempotent: ``sqlite_master`` guards prevent duplicate
table creation, mirroring ``longdoc_schema.py``.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
from typing import Any, Dict, List, Optional

from mnemosyne.extraction.longdoc.security import redact

logger = logging.getLogger(__name__)

_SESSION_TABLE = "chat_sessions"
_TURN_TABLE = "chat_turns"
_SESSION_COLS = ("session_id", "project_hash", "scope_id", "created_at", "status")
_TURN_COLS = ("turn_id", "session_id", "role", "content", "citations", "created_at")

# SPEC-NLQUERY-001 security: per-turn content cap. Bounds storage and the
# synthesis prompt window so a single paste of a large blob cannot exhaust
# memory or token budgets.
MAX_TURN_CONTENT_BYTES = 16 * 1024

# ISSUE-0004 (portion a): conservative default chat-content retention window.
# The TTL value itself is a data-governance decision (portion b) and remains
# human-approval-required; this is only the mechanic default.
DEFAULT_CHAT_RETENTION_DAYS = 90

# Tombstone marker written to ``chat_turns.content`` when the retention purge
# job reclaims a row. The row itself is NEVER deleted (no-delete contract).
RETENTION_PURGED_MARKER = "[retention-purged]"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _index_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def init_chat_schema(conn: sqlite3.Connection) -> bool:
    """Create ``chat_sessions`` + ``chat_turns`` idempotently (REQ-NL-006).

    ISSUE-0004: ``chat_turns`` gains an additive ``retention_purged_at`` column
    (guarded by a PRAGMA check so re-running ``init_chat_schema`` is a no-op)
    plus a ``created_at`` index to keep the retention purge query fast on
    large DBs. No ALTER of existing columns; no backfill; no DELETE.
    """
    cursor = conn.cursor()
    if not _table_exists(conn, _SESSION_TABLE):
        cursor.execute(
            f"""CREATE TABLE {_SESSION_TABLE} (
                session_id TEXT PRIMARY KEY,
                project_hash TEXT,
                scope_id TEXT,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )"""
        )
    if not _table_exists(conn, _TURN_TABLE):
        cursor.execute(
            f"""CREATE TABLE {_TURN_TABLE} (
                turn_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                citations TEXT,
                created_at TEXT NOT NULL,
                retention_purged_at TEXT,
                FOREIGN KEY (session_id)
                    REFERENCES {_SESSION_TABLE}(session_id)
            )"""
        )
        cursor.execute(
            f"CREATE INDEX idx_chat_turns_session ON {_TURN_TABLE}(session_id)"
        )
    # ISSUE-0004: additive column migration for pre-existing DBs. Idempotent:
    # the PRAGMA guard skips once the column is present.
    if _table_exists(conn, _TURN_TABLE) and not _column_exists(
        conn, _TURN_TABLE, "retention_purged_at"
    ):
        cursor.execute(
            f"ALTER TABLE {_TURN_TABLE} ADD COLUMN retention_purged_at TEXT"
        )
    # Purge-query index: WHERE created_at < cutoff AND retention_purged_at IS NULL
    if not _index_exists(conn, "idx_chat_turns_created"):
        cursor.execute(
            f"CREATE INDEX idx_chat_turns_created ON {_TURN_TABLE}(created_at)"
        )
    conn.commit()
    return True


def _utc_now() -> str:
    from mnemosyne.graph.knowledge_graph import utc_now_iso

    return utc_now_iso()


def _col(row: Any, name: str, idx: int) -> Any:
    """Read a column from a sqlite3.Row or a bare tuple."""
    if hasattr(row, "keys"):
        return row[name]
    return row[idx]


def _session_dict(row: Any) -> Dict[str, Any]:
    return {c: _col(row, c, i) for i, c in enumerate(_SESSION_COLS)}


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


_TRUNCATED_MARKER = "[truncated]"


def _cap_turn_content(content: str) -> str:
    """Truncate ``content`` to ``MAX_TURN_CONTENT_BYTES`` (UTF-8) with a marker.

    Slices on byte boundaries then walks back to the last complete UTF-8
    sequence start so we never split a multibyte (CJK) character. The marker
    is appended within the byte budget.
    """
    encoded = content.encode("utf-8")
    if len(encoded) <= MAX_TURN_CONTENT_BYTES:
        return content
    marker_bytes = len(_TRUNCATED_MARKER.encode("utf-8"))
    budget = max(0, MAX_TURN_CONTENT_BYTES - marker_bytes)
    truncated = encoded[:budget]
    # Walk back to the last complete UTF-8 sequence (a byte that is NOT a
    # continuation byte, i.e. does not start with 10xxxxxx).
    while truncated and (truncated[-1] & 0xC0) == 0x80:
        truncated = truncated[:-1]
    head = truncated.decode("utf-8", errors="ignore")
    return head + _TRUNCATED_MARKER


class ChatStore:
    """REQ-NL-006: append-only chat session store (no DELETE/UPDATE on rows)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        init_chat_schema(conn)

    def create_session(
        self,
        project_hash: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> str:
        sid = _gen_id("sess")
        self.conn.execute(
            f"INSERT INTO {_SESSION_TABLE} "
            "(session_id, project_hash, scope_id, created_at, status) "
            "VALUES (?, ?, ?, ?, 'active')",
            (sid, project_hash, scope_id, _utc_now()),
        )
        self.conn.commit()
        return sid

    def get_session(
        self,
        session_id: str,
        project_hash: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a session by id, optionally filtered by ``project_hash``.

        SPEC-NLQUERY-001 security (IDOR): when ``project_hash`` is supplied,
        rows whose ``project_hash`` does not match are treated as not-found.
        Callers receive ``None`` for both missing and mismatched sessions so
        existence is never leaked (404, not 403).
        """
        if project_hash is None:
            row = self.conn.execute(
                f"SELECT {', '.join(_SESSION_COLS)} FROM {_SESSION_TABLE} "
                "WHERE session_id=?",
                (session_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                f"SELECT {', '.join(_SESSION_COLS)} FROM {_SESSION_TABLE} "
                "WHERE session_id=? AND project_hash=?",
                (session_id, project_hash),
            ).fetchone()
        return _session_dict(row) if row is not None else None

    def list_sessions(
        self,
        project_hash: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if project_hash:
            clauses.append("project_hash = ?")
            params.append(project_hash)
        if not include_archived:
            clauses.append("status = 'active'")
        where = " AND ".join(clauses) if clauses else "1=1"
        rows = self.conn.execute(
            f"SELECT {', '.join(_SESSION_COLS)} FROM {_SESSION_TABLE} "
            f"WHERE {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [_session_dict(r) for r in rows]

    def archive_session(self, session_id: str) -> bool:
        """Tombstone: flip status to 'archived'. No row delete (REQ-NL-006)."""
        cur = self.conn.execute(
            f"UPDATE {_SESSION_TABLE} SET status='archived' "
            f"WHERE session_id=? AND status='active'",
            (session_id,),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def append_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Append a turn row. No UPDATE/DELETE path exists for turns.

        SPEC-NLQUERY-001 security: ``content`` is capped at
        ``MAX_TURN_CONTENT_BYTES`` (UTF-8). Oversized content is truncated to
        the cap with a visible ``[truncated]`` marker so the append-only
        contract is preserved and callers are not surprised by mid-chat errors.

        ISSUE-0004: ``content`` is also passed through ``redact()`` (the
        shared inline secret redactor) AFTER the byte cap and BEFORE the
        INSERT. Recognisable credential carriers (GitHub / AWS / JWT / Slack
        tokens, private-key blocks, etc.) are replaced with ``[REDACTED:*]``
        markers so secret-like substrings never land in ``chat_turns`` at
        rest. The 8 original patterns + 2 new (JWT, Slack) total 10. The
        redactor is conservative on free text to avoid false positives.
        """
        content = _cap_turn_content(content)
        content = redact(content)
        turn_id = _gen_id("turn")
        self.conn.execute(
            f"INSERT INTO {_TURN_TABLE} "
            "(turn_id, session_id, role, content, citations, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                turn_id,
                session_id,
                role,
                content,
                json.dumps(citations or []),
                _utc_now(),
            ),
        )
        self.conn.commit()
        return turn_id

    def list_turns(self, session_id: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            f"SELECT {', '.join(_TURN_COLS)} FROM {_TURN_TABLE} "
            "WHERE session_id=? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            raw_cites = _col(r, "citations", 4)
            try:
                cites = json.loads(raw_cites or "[]")
            except (ValueError, TypeError):
                cites = []
            turn = {c: _col(r, c, i) for i, c in enumerate(_TURN_COLS)}
            turn["citations"] = cites
            out.append(turn)
        return out


# ----------------------------------------------------------------------------
# REQ-NL-007: context window + rolling summary
# ----------------------------------------------------------------------------


def build_context_window(
    turns: List[Dict[str, Any]],
    max_turns: Optional[int] = None,
) -> str:
    """Render the last N turns + a single rolling summary line (REQ-NL-007).

    Turns older than the window collapse into one ``[prior N turns summarized]``
    line so the synthesis prompt stays bounded.
    """
    if not turns:
        return ""
    if max_turns is None:
        max_turns = _default_context_turns()
    if max_turns <= 0:
        return ""
    total = len(turns)
    recent = turns[-max_turns:]
    lines: List[str] = []
    if total > max_turns:
        lines.append(f"[prior {total - max_turns} turns summarized]")
    for t in recent:
        role = t.get("role", "user")
        content = str(t.get("content", "")).strip().replace("\n", " ")
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _default_context_turns() -> int:
    import os

    raw = os.environ.get("MNEMOSYNE_CHAT_CONTEXT_TURNS", "")
    if raw:
        try:
            val = int(raw)
            if val > 0:
                return val
        except ValueError:
            logger.warning(
                "MNEMOSYNE_CHAT_CONTEXT_TURNS=%r not a positive int; defaulting to 10",
                raw,
            )
    return 10


# ----------------------------------------------------------------------------
# ISSUE-0004 (portion a): chat-content retention purge
# ----------------------------------------------------------------------------


def retention_days_from_env(default: int = DEFAULT_CHAT_RETENTION_DAYS) -> int:
    """Read ``MNEMOSYNE_CHAT_RETENTION_DAYS`` (positive int) or fall back.

    Non-positive or non-integer values log a warning and return the default.
    The TTL default itself is a data-governance decision (portion b) and
    remains human-approval-required; this helper only resolves the env value.
    """
    raw = os.environ.get("MNEMOSYNE_CHAT_RETENTION_DAYS", "")
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        logger.warning(
            "MNEMOSYNE_CHAT_RETENTION_DAYS=%r not an int; defaulting to %d",
            raw,
            default,
        )
        return default
    if val <= 0:
        logger.warning(
            "MNEMOSYNE_CHAT_RETENTION_DAYS=%r not positive; defaulting to %d",
            raw,
            default,
        )
        return default
    return val


def _utc_now_dt():
    """Return a timezone-aware ``datetime`` for now (UTC)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _cutoff_iso(days: int) -> str:
    """Return the ISO8601 timestamp ``days`` ago.

    Matches the storage shape of ``chat_turns.created_at``: a NAIVE ISO-8601
    string (no ``+00:00`` suffix) produced by ``mnemosyne.timestamps.utc_now_iso``.
    Lexical string comparison on identical-shape ISO strings is a correct
    chronological ordering, so the ``WHERE created_at < cutoff`` predicate
    resolves correctly as long as cutoff has the same naive shape.
    """
    from datetime import timedelta

    cutoff_dt = _utc_now_dt() - timedelta(days=days)
    return cutoff_dt.replace(tzinfo=None).isoformat()


def purge_retention_candidates(
    conn: sqlite3.Connection,
    days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return turns older than ``days`` that have not yet been purged.

    ``days`` defaults to ``MNEMOSYNE_CHAT_RETENTION_DAYS`` (env, default 90).
    A turn is a candidate iff ``created_at < (now - days)`` AND
    ``retention_purged_at IS NULL``. Read-only: performs zero writes.
    """
    if days is None:
        days = retention_days_from_env()
    cutoff_iso = _cutoff_iso(days)
    rows = conn.execute(
        f"SELECT turn_id, session_id, created_at FROM {_TURN_TABLE} "
        f"WHERE created_at < ? AND retention_purged_at IS NULL "
        f"ORDER BY created_at ASC",
        (cutoff_iso,),
    ).fetchall()
    return [
        {
            "turn_id": r[0],
            "session_id": r[1],
            "created_at": r[2],
        }
        for r in rows
    ]


def purge_retention(
    conn: sqlite3.Connection,
    days: Optional[int] = None,
    apply: bool = False,
) -> Dict[str, Any]:
    """Purge chat turns older than the retention window (tombstone-only).

    ISSUE-0004 AC-4: this is the core purge mechanic. NEVER issues a ``DELETE``
    (no-delete contract). Reclaims old turns by:

      - ``UPDATE chat_turns SET retention_purged_at = <now>, content = '[retention-purged]'``
      - ``WHERE created_at < cutoff AND retention_purged_at IS NULL``

    Idempotent: re-running is a no-op once ``retention_purged_at`` is set.

    Args:
        conn: open sqlite3 connection with ``chat_turns`` schema initialised.
        days: retention window in days. Defaults to
            ``MNEMOSYNE_CHAT_RETENTION_DAYS`` (env, default 90).
        apply: if False (default), performs zero writes and only reports the
            candidate turn count + sample IDs. If True, runs the UPDATE
            tombstone and returns the affected row count.

    Returns:
        dict with ``mode`` ("dry-run" | "apply"), ``days``, ``cutoff``,
        ``candidate_count``, ``sample_turn_ids`` (max 10), and (apply only)
        ``purged_count``.
    """
    if days is None:
        days = retention_days_from_env()
    cutoff = _cutoff_iso(days)
    init_chat_schema(conn)
    candidates = purge_retention_candidates(conn, days=days)
    sample = [c["turn_id"] for c in candidates[:10]]
    result: Dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "days": days,
        "cutoff": cutoff,
        "candidate_count": len(candidates),
        "sample_turn_ids": sample,
    }
    if not apply:
        return result
    if not candidates:
        result["purged_count"] = 0
        return result
    now_iso = _utc_now()
    cur = conn.execute(
        f"UPDATE {_TURN_TABLE} "
        f"SET retention_purged_at = ?, content = ? "
        f"WHERE created_at < ? AND retention_purged_at IS NULL",
        (now_iso, RETENTION_PURGED_MARKER, cutoff),
    )
    conn.commit()
    result["purged_count"] = cur.rowcount
    return result

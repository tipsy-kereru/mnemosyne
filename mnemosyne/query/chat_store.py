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
import secrets
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SESSION_TABLE = "chat_sessions"
_TURN_TABLE = "chat_turns"
_SESSION_COLS = ("session_id", "project_hash", "scope_id", "created_at", "status")
_TURN_COLS = ("turn_id", "session_id", "role", "content", "citations", "created_at")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def init_chat_schema(conn: sqlite3.Connection) -> bool:
    """Create ``chat_sessions`` + ``chat_turns`` idempotently (REQ-NL-006)."""
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
                FOREIGN KEY (session_id)
                    REFERENCES {_SESSION_TABLE}(session_id)
            )"""
        )
        cursor.execute(
            f"CREATE INDEX idx_chat_turns_session ON {_TURN_TABLE}(session_id)"
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

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            f"SELECT {', '.join(_SESSION_COLS)} FROM {_SESSION_TABLE} "
            "WHERE session_id=?",
            (session_id,),
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
        """Append a turn row. No UPDATE/DELETE path exists for turns."""
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

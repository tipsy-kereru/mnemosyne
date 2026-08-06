"""SQLite-backed push synchronization state.

Tracks what Mnemosyne has pushed to Onyx so that:

- Same content hash is a no-op (§3 rule 2).
- API *accepted* and *indexed* are recorded as separate states (Phase 1
  principle: "API accepted와 indexed를 별도 상태로 기록").
- Retry attempts and errors are persisted for observability.

The table lives in the same SQLite database as the knowledge graph,
added idempotently on first use.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PUSH_PENDING = "pending"
PUSH_ACCEPTED = "accepted"
PUSH_INDEXED = "indexed"
PUSH_FAILED = "failed"
PUSH_NOOP = "noop"
PUSH_WITHDRAW_PENDING = "withdraw_pending"
PUSH_WITHDRAW_BLOCKED = "withdraw_blocked"
PUSH_WITHDRAWN = "withdrawn"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PushState:
    """Snapshot of one document's push state."""

    document_id: str
    scope_id: str = ""
    entity_type: str = ""
    entity_id: str = ""
    status: str = PUSH_PENDING
    content_hash: str = ""
    pushed_at: Optional[str] = None
    accepted_at: Optional[str] = None
    indexed_at: Optional[str] = None
    error: str = ""
    attempts: int = 0


@dataclass(frozen=True)
class PreflightRecord:
    scope_id: str
    destination_id: str
    destination_fingerprint: str
    reviewed_at: str
    actor: str
    candidate_count: int
    deny_count: int

class SyncStateStore:
    """Persists push state in a SQLite table alongside the KG."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, timeout=30.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self) -> None:
        c = self.conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS onyx_push_state (
                document_id   TEXT PRIMARY KEY,
                scope_id      TEXT NOT NULL DEFAULT '',
                entity_type   TEXT NOT NULL DEFAULT '',
                entity_id     TEXT NOT NULL DEFAULT '',
                status        TEXT NOT NULL DEFAULT 'pending',
                content_hash  TEXT NOT NULL DEFAULT '',
                pushed_at     TEXT,
                accepted_at   TEXT,
                indexed_at    TEXT,
                error         TEXT NOT NULL DEFAULT '',
                attempts      INTEGER NOT NULL DEFAULT 0
            )
        ''')
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_onyx_push_scope "
            "ON onyx_push_state(scope_id)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_onyx_push_status "
            "ON onyx_push_state(status)"
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS onyx_preflight (
                scope_id TEXT PRIMARY KEY,
                destination_id TEXT NOT NULL,
                destination_fingerprint TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                candidate_count INTEGER NOT NULL,
                deny_count INTEGER NOT NULL
            )"""
        )
        self.conn.commit()

    def get(self, document_id: str) -> Optional[PushState]:
        row = self.conn.execute(
            "SELECT * FROM onyx_push_state WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        return PushState(
            document_id=row["document_id"],
            scope_id=row["scope_id"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            status=row["status"],
            content_hash=row["content_hash"],
            pushed_at=row["pushed_at"],
            accepted_at=row["accepted_at"],
            indexed_at=row["indexed_at"],
            error=row["error"],
            attempts=row["attempts"],
        )

    def is_noop(self, document_id: str, content_hash: str) -> bool:
        """True when this exact hash was already accepted/indexed."""
        state = self.get(document_id)
        if state is None:
            return False
        if state.status not in (PUSH_ACCEPTED, PUSH_INDEXED, PUSH_NOOP):
            return False
        return state.content_hash == content_hash

    def record_push(
        self,
        document_id: str,
        scope_id: str,
        entity_type: str,
        entity_id: str,
        content_hash: str,
    ) -> PushState:
        """Record that a push attempt is starting (or update attempts)."""
        existing = self.get(document_id)
        attempts = (existing.attempts + 1) if existing else 1
        now = _utc_now()
        self.conn.execute('''
            INSERT INTO onyx_push_state
                (document_id, scope_id, entity_type, entity_id, status,
                 content_hash, pushed_at, attempts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                scope_id     = excluded.scope_id,
                entity_type  = excluded.entity_type,
                entity_id    = excluded.entity_id,
                status       = excluded.status,
                content_hash = excluded.content_hash,
                pushed_at    = excluded.pushed_at,
                attempts     = excluded.attempts
        ''', (
            document_id, scope_id, entity_type, entity_id,
            PUSH_PENDING, content_hash, now, attempts,
        ))
        self.conn.commit()
        return self.get(document_id)  # type: ignore[return-value]

    def mark_noop(self, document_id: str) -> None:
        self._update_status(document_id, PUSH_NOOP)

    def mark_accepted(self, document_id: str) -> None:
        self._update_status(document_id, PUSH_ACCEPTED, accepted=True)

    def mark_indexed(self, document_id: str) -> None:
        self._update_status(document_id, PUSH_INDEXED, indexed=True)

    def mark_failed(self, document_id: str, error: str) -> None:
        self.conn.execute(
            "UPDATE onyx_push_state SET status = ?, error = ? WHERE document_id = ?",
            (PUSH_FAILED, error, document_id),
        )
        self.conn.commit()

    def _update_status(
        self,
        document_id: str,
        status: str,
        accepted: bool = False,
        indexed: bool = False,
    ) -> None:
        now = _utc_now()
        sets = ["status = ?"]
        params: list[Any] = [status]
        if accepted:
            sets.append("accepted_at = ?")
            params.append(now)
        if indexed:
            sets.append("indexed_at = ?")
            params.append(now)
        params.append(document_id)
        self.conn.execute(
            f"UPDATE onyx_push_state SET {', '.join(sets)} WHERE document_id = ?",
            params,
        )
        self.conn.commit()
    def list_scope(self, scope_id: str) -> list[PushState]:
        rows = self.conn.execute(
            "SELECT * FROM onyx_push_state WHERE scope_id=?",
            (scope_id,),
        ).fetchall()
        return [
            PushState(
                document_id=row["document_id"], scope_id=row["scope_id"],
                entity_type=row["entity_type"], entity_id=row["entity_id"],
                status=row["status"], content_hash=row["content_hash"],
                pushed_at=row["pushed_at"], accepted_at=row["accepted_at"],
                indexed_at=row["indexed_at"], error=row["error"],
                attempts=row["attempts"],
            )
            for row in rows
        ]

    def mark_withdraw_blocked(self, document_id: str, reason: str) -> None:
        self._update_status(document_id, PUSH_WITHDRAW_BLOCKED)
        self.conn.execute(
            "UPDATE onyx_push_state SET error=? WHERE document_id=?",
            (reason, document_id),
        )
        self.conn.commit()

    def mark_withdrawn(self, document_id: str) -> None:
        self._update_status(document_id, PUSH_WITHDRAWN)

    def record_preflight(self, record: PreflightRecord) -> None:
        self.conn.execute(
            """INSERT INTO onyx_preflight
               (scope_id, destination_id, destination_fingerprint,
                reviewed_at, actor, candidate_count, deny_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(scope_id) DO UPDATE SET
                 destination_id=excluded.destination_id,
                 destination_fingerprint=excluded.destination_fingerprint,
                 reviewed_at=excluded.reviewed_at, actor=excluded.actor,
                 candidate_count=excluded.candidate_count,
                 deny_count=excluded.deny_count""",
            (
                record.scope_id, record.destination_id,
                record.destination_fingerprint, record.reviewed_at,
                record.actor, record.candidate_count, record.deny_count,
            ),
        )
        self.conn.commit()

    def get_preflight(self, scope_id: str) -> Optional[PreflightRecord]:
        row = self.conn.execute(
            "SELECT * FROM onyx_preflight WHERE scope_id=?", (scope_id,)
        ).fetchone()
        if row is None:
            return None
        return PreflightRecord(
            scope_id=row["scope_id"],
            destination_id=row["destination_id"],
            destination_fingerprint=row["destination_fingerprint"],
            reviewed_at=row["reviewed_at"],
            actor=row["actor"],
            candidate_count=row["candidate_count"],
            deny_count=row["deny_count"],
        )

    def get_scope_summary(self, scope_id: str) -> dict[str, Any]:
        """Aggregate push state for a scope (for `sync status`)."""
        rows = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM onyx_push_state "
            "WHERE scope_id = ? GROUP BY status",
            (scope_id,),
        ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        total = sum(counts.values())
        last_pushed = self.conn.execute(
            "SELECT MAX(pushed_at) as latest FROM onyx_push_state WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()
        return {
            "scope_id": scope_id,
            "total_documents": total,
            "by_status": counts,
            "last_pushed_at": last_pushed["latest"] if last_pushed else None,
        }

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

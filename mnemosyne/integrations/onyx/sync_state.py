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

# Push lifecycle states (§4 state machine subset for the push direction).
PUSH_PENDING = "pending"        # queued, not yet sent
PUSH_ACCEPTED = "accepted"      # Onyx API returned 200
PUSH_INDEXED = "indexed"        # confirmed in Onyx index
PUSH_FAILED = "failed"          # terminal failure after retries
PUSH_NOOP = "noop"              # same content hash, skipped


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

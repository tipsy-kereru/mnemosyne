"""SQLite-backed checkpoint/watermark store for the Onyx → Mnemosyne
Export Worker (Phase 2).

Tracks per-connector progress so that:

- Incremental collection resumes from the last watermark (§6 Phase 2:
  "중단 후 checkpoint부터 재개").
- A crash or restart does not re-process already-synced documents.
- Stale connectors — not synced within the TTL window — are surfaced for
  operators (§5 observability: "마지막 성공 시각, 처리량, ... stale 수").

The table lives in the same SQLite database as the knowledge graph and
the push state store, created idempotently on first use. WAL mode and
``row_factory = sqlite3.Row`` mirror :mod:`sync_state`.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Checkpoint:
    """Snapshot of one connector's export progress."""

    connector_id: str
    scope_id: str = ""
    last_watermark: str = ""
    last_sync_at: Optional[str] = None
    documents_processed: int = 0
    last_error: str = ""


class CheckpointStore:
    """Persists per-connector checkpoints alongside the KG.

    Args:
        db_path: Path to the SQLite database (shared with the KG and
            push state store). Use ``":memory:"`` only for tests that
            keep a single long-lived connection.
    """

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
            CREATE TABLE IF NOT EXISTS onyx_export_checkpoint (
                connector_id        TEXT PRIMARY KEY,
                scope_id            TEXT NOT NULL DEFAULT '',
                last_watermark      TEXT NOT NULL DEFAULT '',
                last_sync_at        TEXT,
                documents_processed INTEGER NOT NULL DEFAULT 0,
                last_error          TEXT NOT NULL DEFAULT ''
            )
        ''')
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_onyx_checkpoint_scope "
            "ON onyx_export_checkpoint(scope_id)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_onyx_checkpoint_sync "
            "ON onyx_export_checkpoint(last_sync_at)"
        )
        self.conn.commit()

    # ── Read ──────────────────────────────────────────────────────

    def get(self, connector_id: str) -> Optional[Checkpoint]:
        """Return the checkpoint for ``connector_id``, or ``None``."""
        row = self.conn.execute(
            "SELECT * FROM onyx_export_checkpoint WHERE connector_id = ?",
            (connector_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_checkpoint(row)

    # ── Write ─────────────────────────────────────────────────────

    def save(
        self,
        connector_id: str,
        scope_id: str,
        watermark: str,
        docs_processed: int,
    ) -> Checkpoint:
        """Upsert a connector checkpoint.

        Advances the watermark, refreshes ``last_sync_at``, sets the
        processed count, and clears any prior error.
        """
        now = _utc_now()
        self.conn.execute('''
            INSERT INTO onyx_export_checkpoint
                (connector_id, scope_id, last_watermark, last_sync_at,
                 documents_processed, last_error)
            VALUES (?, ?, ?, ?, ?, '')
            ON CONFLICT(connector_id) DO UPDATE SET
                scope_id            = excluded.scope_id,
                last_watermark      = excluded.last_watermark,
                last_sync_at        = excluded.last_sync_at,
                documents_processed = excluded.documents_processed,
                last_error          = ''
        ''', (connector_id, scope_id, watermark, now, docs_processed))
        self.conn.commit()
        return self.get(connector_id)  # type: ignore[return-value]

    def advance(self, connector_id: str, watermark: str) -> None:
        """Advance the watermark only, refreshing ``last_sync_at``.

        Does not touch ``documents_processed`` or ``last_error``.
        """
        now = _utc_now()
        self.conn.execute(
            "UPDATE onyx_export_checkpoint "
            "SET last_watermark = ?, last_sync_at = ? "
            "WHERE connector_id = ?",
            (watermark, now, connector_id),
        )
        self.conn.commit()

    def record_error(self, connector_id: str, error: str) -> None:
        """Record an error without moving the successful watermark."""
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO onyx_export_checkpoint
                (connector_id, last_sync_at, last_error)
            VALUES (?, ?, ?)
            ON CONFLICT(connector_id) DO UPDATE SET
                last_error = ?, last_sync_at = ?
            """,
            (connector_id, now, error, error, now),
        )
        self.conn.commit()

    def list_stale(self, ttl_hours: int = 24) -> list[Checkpoint]:
        """Return connectors not synced within the TTL window.

        A connector with no ``last_sync_at`` (never synced) or an
        unparseable timestamp is always considered stale.
        """
        rows = self.conn.execute(
            "SELECT * FROM onyx_export_checkpoint"
        ).fetchall()
        now = datetime.now(timezone.utc)
        stale: list[Checkpoint] = []
        for row in rows:
            cp = _row_to_checkpoint(row)
            if not cp.last_sync_at:
                stale.append(cp)
                continue
            try:
                synced = datetime.fromisoformat(cp.last_sync_at)
            except (ValueError, TypeError):
                stale.append(cp)
                continue
            age = (now - synced).total_seconds() / 3600
            if age > ttl_hours:
                stale.append(cp)
        return stale

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def _row_to_checkpoint(row: sqlite3.Row) -> Checkpoint:
    return Checkpoint(
        connector_id=row["connector_id"],
        scope_id=row["scope_id"],
        last_watermark=row["last_watermark"],
        last_sync_at=row["last_sync_at"],
        documents_processed=row["documents_processed"],
        last_error=row["last_error"],
    )

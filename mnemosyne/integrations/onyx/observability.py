"""Observability queries for Onyx sync operations.

Phase 5 §6 metrics:
- 마지막 성공 시각 (last success time)
- 처리량 (throughput — total documents processed)
- 실패율 (failure rate)
- quarantine 수 (unresolved quarantine count)
- stale 수 (stale checkpoint count)

All queries are read-only against the sync tables created by
:class:`SyncStateStore`, :class:`CheckpointStore`, and
:class:`ExportWorker`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SyncMetrics:
    """Aggregate observability snapshot for a scope."""

    scope_id: str
    # Push direction (Mnemosyne → Onyx)
    push_total: int = 0
    push_accepted: int = 0
    push_failed: int = 0
    push_noop: int = 0
    push_last_at: Optional[str] = None
    # Export direction (Onyx → Mnemosyne)
    export_ingested: int = 0
    export_quarantined: int = 0
    export_rejected: int = 0
    export_last_watermark: Optional[str] = None
    # Quarantine
    quarantine_unresolved: int = 0
    quarantine_total: int = 0
    # Stale connectors
    stale_connectors: int = 0

    @property
    def push_failure_rate(self) -> float:
        if self.push_total == 0:
            return 0.0
        return self.push_failed / self.push_total

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "push": {
                "total": self.push_total,
                "accepted": self.push_accepted,
                "failed": self.push_failed,
                "noop": self.push_noop,
                "failure_rate": round(self.push_failure_rate, 4),
                "last_at": self.push_last_at,
            },
            "export": {
                "ingested": self.export_ingested,
                "quarantined": self.export_quarantined,
                "rejected": self.export_rejected,
                "last_watermark": self.export_last_watermark,
            },
            "quarantine": {
                "unresolved": self.quarantine_unresolved,
                "total": self.quarantine_total,
            },
            "stale_connectors": self.stale_connectors,
        }


def get_sync_metrics(
    conn: sqlite3.Connection, scope_id: str
) -> SyncMetrics:
    """Compute aggregate observability metrics for a scope."""
    metrics = SyncMetrics(scope_id=scope_id)

    # ── Push state ──
    if _table_exists(conn, "onyx_push_state"):
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM onyx_push_state "
            "WHERE scope_id = ? GROUP BY status",
            (scope_id,),
        ).fetchall()
        for row in rows:
            status, cnt = row["status"], row["cnt"]
            metrics.push_total += cnt
            if status == "accepted":
                metrics.push_accepted += cnt
            elif status == "failed":
                metrics.push_failed += cnt
            elif status == "noop":
                metrics.push_noop += cnt

        last = conn.execute(
            "SELECT MAX(pushed_at) as latest FROM onyx_push_state WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()
        metrics.push_last_at = last["latest"] if last else None

    # ── Export checkpoint ──
    if _table_exists(conn, "onyx_export_checkpoint"):
        cp = conn.execute(
            "SELECT last_watermark FROM onyx_export_checkpoint WHERE scope_id = ? "
            "ORDER BY last_sync_at DESC LIMIT 1",
            (scope_id,),
        ).fetchone()
        if cp:
            metrics.export_last_watermark = cp["last_watermark"]

    # ── Export source index (ingested/rejected counts) ──
    if _table_exists(conn, "onyx_source_index"):
        ingested = conn.execute(
            "SELECT COUNT(*) as cnt FROM onyx_source_index WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()
        metrics.export_ingested = ingested["cnt"] if ingested else 0

    # ── Quarantine ──
    if _table_exists(conn, "onyx_quarantine"):
        q_total = conn.execute(
            "SELECT COUNT(*) as cnt FROM onyx_quarantine WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()
        metrics.quarantine_total = q_total["cnt"] if q_total else 0

        q_unresolved = conn.execute(
            "SELECT COUNT(*) as cnt FROM onyx_quarantine "
            "WHERE scope_id = ? AND resolved = 0",
            (scope_id,),
        ).fetchone()
        metrics.quarantine_unresolved = q_unresolved["cnt"] if q_unresolved else 0
        metrics.export_quarantined = metrics.quarantine_unresolved

    return metrics


@dataclass
class QuarantineEntry:
    """One unresolved quarantine record."""

    source_doc_id: str
    scope_id: str
    reason: str
    quarantined_at: str
    envelope_snapshot: dict[str, Any] = field(default_factory=dict)
    resolved: bool = False


def get_quarantine_list(
    conn: sqlite3.Connection, scope_id: str, include_resolved: bool = False
) -> list[QuarantineEntry]:
    """List quarantine records for a scope."""
    if not _table_exists(conn, "onyx_quarantine"):
        return []

    if include_resolved:
        rows = conn.execute(
            "SELECT * FROM onyx_quarantine WHERE scope_id = ? "
            "ORDER BY quarantined_at DESC",
            (scope_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM onyx_quarantine WHERE scope_id = ? AND resolved = 0 "
            "ORDER BY quarantined_at DESC",
            (scope_id,),
        ).fetchall()

    entries = []
    for row in rows:
        snapshot = {}
        raw = row["envelope_snapshot"]
        if raw:
            try:
                snapshot = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        entries.append(QuarantineEntry(
            source_doc_id=row["source_doc_id"],
            scope_id=row["scope_id"],
            reason=row["reason"],
            quarantined_at=row["quarantined_at"],
            envelope_snapshot=snapshot,
            resolved=bool(row["resolved"]),
        ))
    return entries


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Check if a table exists (tables are created lazily by sync modules)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None

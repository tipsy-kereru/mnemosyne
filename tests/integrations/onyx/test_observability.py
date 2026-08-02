"""Tests for observability metrics and quarantine listing (Phase 5 §6)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mnemosyne.integrations.onyx.observability import (
    get_quarantine_list,
    get_sync_metrics,
)
from mnemosyne.integrations.onyx.sync_state import SyncStateStore


@pytest.fixture
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    """KG-like connection with sync tables seeded."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute('''
        CREATE TABLE entities (
            id TEXT PRIMARY KEY, type TEXT, name TEXT,
            properties TEXT, created_at TEXT, updated_at TEXT,
            version INTEGER DEFAULT 1, scope_id TEXT, source_channel TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE onyx_push_state (
            document_id TEXT PRIMARY KEY, scope_id TEXT,
            entity_type TEXT, entity_id TEXT, status TEXT,
            content_hash TEXT, pushed_at TEXT, accepted_at TEXT,
            indexed_at TEXT, error TEXT, attempts INTEGER DEFAULT 0
        )
    ''')
    return conn


class TestSyncMetrics:
    def test_empty_db_returns_zeros(self, db_conn):
        metrics = get_sync_metrics(db_conn, "scope-1")
        assert metrics.push_total == 0
        assert metrics.push_failure_rate == 0.0
        assert metrics.quarantine_unresolved == 0

    def test_metrics_from_push_state(self, db_conn, tmp_path):
        store = SyncStateStore(tmp_path / "test.db")
        # Seed some push states
        for i in range(5):
            store.record_push(f"doc-{i}", "scope-1", "decision", f"e-{i}", f"hash-{i}")
        for i in range(3):
            store.mark_accepted(f"doc-{i}")
        store.mark_failed(f"doc-3", "timeout")
        store.mark_noop(f"doc-4")

        # Copy push state into our in-memory conn
        for row in store.conn.execute("SELECT * FROM onyx_push_state").fetchall():
            db_conn.execute(
                "INSERT OR REPLACE INTO onyx_push_state VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                tuple(row),
            )
        db_conn.commit()
        store.close()

        metrics = get_sync_metrics(db_conn, "scope-1")
        assert metrics.push_total == 5
        assert metrics.push_accepted == 3
        assert metrics.push_failed == 1
        assert metrics.push_noop == 1
        assert metrics.push_failure_rate == pytest.approx(0.2)

    def test_metrics_to_dict_structure(self, db_conn):
        metrics = get_sync_metrics(db_conn, "scope-1")
        d = metrics.to_dict()
        assert "push" in d
        assert "export" in d
        assert "quarantine" in d
        assert d["push"]["failure_rate"] == 0.0


class TestQuarantineList:
    def test_empty_returns_empty_list(self, db_conn):
        entries = get_quarantine_list(db_conn, "scope-1")
        assert entries == []

    def test_lists_unresolved_quarantine(self, db_conn):
        # Create quarantine table (as ExportWorker would)
        db_conn.execute('''
            CREATE TABLE IF NOT EXISTS onyx_quarantine (
                source_doc_id TEXT PRIMARY KEY, scope_id TEXT, reason TEXT,
                quarantined_at TEXT, envelope_snapshot TEXT,
                resolved INTEGER DEFAULT 0, resolved_at TEXT, resolution TEXT
            )
        ''')
        db_conn.execute(
            "INSERT INTO onyx_quarantine VALUES (?, ?, ?, ?, ?, 0, NULL, NULL)",
            ("doc-1", "scope-1", "ACL empty", "2026-08-02T10:00:00Z",
             json.dumps({"title": "Decision A", "external_uri": "https://a.com"})),
        )
        db_conn.execute(
            "INSERT INTO onyx_quarantine VALUES (?, ?, ?, ?, ?, 1, '2026-08-02T11:00:00Z', 'accepted')",
            ("doc-2", "scope-1", "stale ACL", "2026-08-01T10:00:00Z",
             json.dumps({"title": "Decision B"})),
        )
        db_conn.commit()

        # Default: unresolved only
        entries = get_quarantine_list(db_conn, "scope-1")
        assert len(entries) == 1
        assert entries[0].source_doc_id == "doc-1"
        assert entries[0].reason == "ACL empty"
        assert entries[0].resolved is False
        assert entries[0].envelope_snapshot["title"] == "Decision A"

        # With --all: include resolved
        all_entries = get_quarantine_list(db_conn, "scope-1", include_resolved=True)
        assert len(all_entries) == 2

    def test_scope_isolation(self, db_conn):
        db_conn.execute('''
            CREATE TABLE IF NOT EXISTS onyx_quarantine (
                source_doc_id TEXT PRIMARY KEY, scope_id TEXT, reason TEXT,
                quarantined_at TEXT, envelope_snapshot TEXT,
                resolved INTEGER DEFAULT 0, resolved_at TEXT, resolution TEXT
            )
        ''')
        db_conn.execute(
            "INSERT INTO onyx_quarantine VALUES (?, ?, ?, ?, ?, 0, NULL, NULL)",
            ("doc-1", "scope-a", "reason", "2026-08-02", "{}"),
        )
        db_conn.execute(
            "INSERT INTO onyx_quarantine VALUES (?, ?, ?, ?, ?, 0, NULL, NULL)",
            ("doc-2", "scope-b", "reason", "2026-08-02", "{}"),
        )
        db_conn.commit()

        assert len(get_quarantine_list(db_conn, "scope-a")) == 1
        assert len(get_quarantine_list(db_conn, "scope-b")) == 1

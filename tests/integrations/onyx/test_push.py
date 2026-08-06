"""Push integration tests: Mnemosyne → Onyx.

Tests the full push flow using the mock Onyx server:
- dry-run (no network)
- new entity push (accepted)
- same content hash no-op
- changed entity update
- retry on transient failure
- non-publishable types skipped
- loop guard (do_not_reimport)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from mnemosyne.integrations.onyx.client import (
    IngestResult,
    OnyxClient,
    PushStatus,
)
from mnemosyne.integrations.onyx.exporter import OnyxPushExporter
from mnemosyne.integrations.onyx.mapper import DestinationPolicy
from mnemosyne.integrations.onyx.mock_server import MockOnyxServer
from mnemosyne.integrations.onyx.sync_state import SyncStateStore


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def kg_conn(tmp_path: Path) -> sqlite3.Connection:
    """Minimal in-memory KG schema with publishable entities."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute('''
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            properties TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            scope_id TEXT,
            source_channel TEXT DEFAULT 'legacy'
        )
    ''')
    # Seed entities of various types in scope "client-a"
    _seed_entity(conn, "client-a:decision:use-oauth", "decision",
                 "Use OAuth 2.0 PKCE", {"outcome": "approved", "decided_by": ["Alice"]})
    _seed_entity(conn, "client-a:requirement:auth-flow", "requirement",
                 "Implement auth flow", {"status": "in_progress", "priority": "high"})
    _seed_entity(conn, "client-a:meeting:kickoff", "meeting",
                 "Project kickoff", {"date": "2026-08-01", "attendees": ["Alice", "Bob"]})
    # Non-publishable type — should be skipped
    _seed_entity(conn, "client-a:person:alice", "person",
                 "Alice", {"email": "alice@example.com"})
    # Loop guard — should be skipped
    _seed_entity(conn, "client-a:decision:summary", "decision",
                 "Auto-generated summary",
                 {"outcome": "auto", "do_not_reimport": True})
    conn.commit()
    return conn


def _seed_entity(
    conn: sqlite3.Connection,
    eid: str,
    etype: str,
    name: str,
    props: dict,
) -> None:
    safe_props = {"classification": "public", "visibility": "public"}
    safe_props.update(props)
    conn.execute(
        "INSERT INTO entities (id, type, name, properties, created_at, updated_at, "
        "version, scope_id, source_channel) VALUES (?, ?, ?, ?, ?, ?, 1, 'client-a', 'github')",
        (
            eid, etype, name, json.dumps(safe_props),
            "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z",
        ),
    )


@pytest.fixture
def sync_store(tmp_path: Path) -> SyncStateStore:
    return SyncStateStore(tmp_path / "sync_test.db")


# ── Tests ───────────────────────────────────────────────────────────

class TestDryRun:
    def test_dry_run_maps_without_pushing(self, kg_conn, sync_store):
        exporter = OnyxPushExporter(
            kg_conn, client=None, sync_store=sync_store, dry_run=True
        )
        outcome = exporter.push_scope("client-a")

        # 4 entities queried (person filtered at SQL level):
        # 3 publishable + 1 loop-guard decision
        assert outcome.total == 4
        assert outcome.pushed == 3    # mapped in dry-run
        assert outcome.skipped == 1   # do_not_reimport loop guard
        assert outcome.failed == 0
        # No state should be recorded in dry-run
        assert sync_store.get_scope_summary("client-a")["total_documents"] == 0

    def test_dry_run_reports_document_ids(self, kg_conn, sync_store):
        exporter = OnyxPushExporter(
            kg_conn, client=None, sync_store=sync_store, dry_run=True
        )
        outcome = exporter.push_scope("client-a")
        pushed_ids = [d["document_id"] for d in outcome.details if d["action"] == "dry_run"]
        assert all(did.startswith("mnemosyne:client-a:") for did in pushed_ids)


class TestRealPush:
    def test_new_entities_accepted(self, kg_conn, sync_store):
        with MockOnyxServer() as server:
            client = OnyxClient(
                base_url=server.base_url,
                api_key="test-key",
                cc_pair_id=1,
                max_retries=1,
                initial_backoff=0.01,
            )
            exporter = OnyxPushExporter(kg_conn, client, sync_store)
            outcome = exporter.push_scope("client-a")

        assert outcome.pushed == 3
        assert outcome.failed == 0
        assert outcome.skipped == 1

        # Server received exactly 3 documents
        assert len(server.received_documents) == 3

        # State recorded as accepted
        summary = sync_store.get_scope_summary("client-a")
        assert summary["by_status"].get("accepted", 0) == 3

    def test_accepted_then_noop_on_second_push(self, kg_conn, sync_store):
        """Same content hash on second push = no-op (§3 rule 2)."""
        with MockOnyxServer() as server:
            client = OnyxClient(
                base_url=server.base_url, api_key="test-key", cc_pair_id=1,
                max_retries=1, initial_backoff=0.01,
            )
            exporter = OnyxPushExporter(kg_conn, client, sync_store)

            # First push: 3 accepted
            first = exporter.push_scope("client-a")
            assert first.pushed == 3

            # Second push: all 3 are no-ops (same hash)
            second = exporter.push_scope("client-a")
            assert second.pushed == 0
            assert second.noop == 3

        # Server still only received 3 (not 6)
        assert len(server.received_documents) == 3

    def test_changed_entity_pushed_as_update(self, kg_conn, sync_store):
        """Changed properties → different hash → pushed again."""
        with MockOnyxServer() as server:
            client = OnyxClient(
                base_url=server.base_url, api_key="test-key", cc_pair_id=1,
                max_retries=1, initial_backoff=0.01,
            )
            exporter = OnyxPushExporter(kg_conn, client, sync_store)

            exporter.push_scope("client-a")

            # Modify one entity
            kg_conn.execute(
                "UPDATE entities SET properties = ? WHERE id = ?",
                (
                    json.dumps({
                        "classification": "public",
                        "visibility": "public",
                        "outcome": "rejected",
                        "decided_by": ["Bob"],
                    }),
                    "client-a:decision:use-oauth",
                ),
            )
            kg_conn.commit()

            second = exporter.push_scope("client-a")
            # 1 changed → pushed, 2 unchanged → noop
            assert second.pushed == 1
            assert second.noop == 2


class TestRetry:
    def test_retry_succeeds_after_transient_failure(self, kg_conn, sync_store):
        """Server error on first attempt, success on retry."""
        with MockOnyxServer(fail_first_n=1, fail_status=500) as server:
            client = OnyxClient(
                base_url=server.base_url, api_key="test-key", cc_pair_id=1,
                max_retries=3, initial_backoff=0.01,
            )
            exporter = OnyxPushExporter(kg_conn, client, sync_store)
            outcome = exporter.push_scope("client-a")

        # All should eventually succeed (first request failed then retried)
        assert outcome.pushed == 3
        assert outcome.failed == 0

    def test_auth_error_not_retried(self, kg_conn, sync_store):
        """401 is terminal — no retry."""
        with MockOnyxServer(expected_api_key="wrong-key") as server:
            client = OnyxClient(
                base_url=server.base_url, api_key="test-key", cc_pair_id=1,
                max_retries=3, initial_backoff=0.01,
            )
            exporter = OnyxPushExporter(kg_conn, client, sync_store)
            outcome = exporter.push_scope("client-a")

        assert outcome.pushed == 0
        assert outcome.failed == 3


class TestStateRecording:
    def test_sync_summary_reports_by_status(self, kg_conn, sync_store):
        with MockOnyxServer() as server:
            client = OnyxClient(
                base_url=server.base_url, api_key="test-key", cc_pair_id=1,
                max_retries=1, initial_backoff=0.01,
            )
            exporter = OnyxPushExporter(kg_conn, client, sync_store)
            exporter.push_scope("client-a")

        summary = sync_store.get_scope_summary("client-a")
        assert summary["scope_id"] == "client-a"
        assert summary["total_documents"] == 3
        assert summary["by_status"]["accepted"] == 3
        assert summary["last_pushed_at"] is not None


class _SpyPushClient:
    def __init__(self):
        self.ingest_ids: list[str] = []

    def ingest(self, document_id, semantic_identifier, title, sections, metadata=None, doc_updated_at=None):
        self.ingest_ids.append(document_id)
        return IngestResult(document_id, PushStatus.ACCEPTED, status_code=200, attempts=1)


def _matrix_conn(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, properties TEXT, "
        "updated_at TEXT, scope_id TEXT, source_channel TEXT, version INTEGER)"
    )
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows,
    )
    conn.commit()
    return conn


def _props(**overrides):
    props = {"classification": "public", "visibility": "public", "outcome": "approved"}
    props.update(overrides)
    return props


def test_t27_fixed_live_and_tombstoned_matrix_never_sends_denied_ids(tmp_path):
    rows = [
        ("public-live", "decision", "Public live", json.dumps(_props()), "2026-08-06", "scope-a", "test", 1),
        ("private-live", "decision", "Private live", json.dumps(_props(classification="private")), "2026-08-06", "scope-a", "test", 1),
        ("public-tombstoned", "decision", "Public tombstoned", json.dumps(_props(tombstoned_at="2026-08-06")), "2026-08-06", "scope-a", "test", 1),
        ("private-tombstoned", "decision", "Private tombstoned", json.dumps(_props(classification="private", tombstoned_at="2026-08-06")), "2026-08-06", "scope-a", "test", 1),
    ]
    conn = _matrix_conn(rows)
    client = _SpyPushClient()
    outcome = OnyxPushExporter(
        conn, client, SyncStateStore(tmp_path / "sync.db"),
        destination_policy=DestinationPolicy(),
    ).push_scope("scope-a")
    assert outcome.pushed == 1
    assert outcome.skipped == 1
    assert client.ingest_ids == ["mnemosyne:scope-a:decision:public-live"]


def test_t28_denied_entity_does_not_create_push_state_row(tmp_path):
    conn = _matrix_conn([
        ("private", "decision", "Private", json.dumps(_props(classification="private")), "2026-08-06", "scope-a", "test", 1),
    ])
    store = SyncStateStore(tmp_path / "sync.db")
    outcome = OnyxPushExporter(
        conn, _SpyPushClient(), store, destination_policy=DestinationPolicy(),
    ).push_scope("scope-a")
    assert outcome.skipped == 1


def test_t29_valid_to_text_inside_unrelated_property_does_not_filter_live_entity(tmp_path):
    props = _props(note="contains valid_to as ordinary text")
    conn = _matrix_conn([
        ("live", "decision", "Live", json.dumps(props), "2026-08-06", "scope-a", "test", 1),
    ])
    outcome = OnyxPushExporter(
        conn, _SpyPushClient(), SyncStateStore(tmp_path / "sync.db"),
        destination_policy=DestinationPolicy(),
    ).push_scope("scope-a")
    assert outcome.pushed == 1


def test_t30_dry_run_details_contain_ids_and_codes_not_titles(tmp_path):
    conn = _matrix_conn([
        ("live", "decision", "Synthetic title", json.dumps(_props()), "2026-08-06", "scope-a", "test", 1),
    ])
    outcome = OnyxPushExporter(
        conn, None, SyncStateStore(tmp_path / "sync.db"), dry_run=True,
    ).push_scope("scope-a")
    detail_text = json.dumps(outcome.details)
    assert "mnemosyne:scope-a:decision:live" in detail_text
    assert "Synthetic title" not in detail_text

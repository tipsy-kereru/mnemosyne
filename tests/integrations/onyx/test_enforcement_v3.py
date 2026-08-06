from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import get_type_hints

from mnemosyne.integrations.onyx.client import IngestResult, PushStatus
from mnemosyne.integrations.onyx.config import SyncConfig
from mnemosyne.integrations.onyx.destinations import (
    DestinationNotBound,
    DestinationRegistry,
)
from mnemosyne.integrations.onyx.exporter import OnyxPushExporter
from mnemosyne.integrations.onyx.mapper import DestinationPolicy, map_entity
from mnemosyne.integrations.onyx.sync_state import SyncStateStore
from mnemosyne.integrations.onyx.worker import _safe_watermark


def test_scope_binding_and_secret_free_fingerprint():
    cfg = SyncConfig.from_dict({
        "destinations": {
            "a": {
                "base_url": "https://onyx.example",
                "api_key_env": "KEY",
                "cc_pair_id_env": "CC",
                "approved_hosts": ["onyx.example"],
            }
        },
        "scope_bindings": [{"scope_id": "alpha", "destination": "a"}],
    })
    destination = DestinationRegistry.from_config(cfg).for_scope("alpha")
    assert destination.policy().classification_ceiling == "public"
    assert "secret-value" not in destination.fingerprint()
    try:
        DestinationRegistry.from_config(cfg).for_scope("beta")
    except DestinationNotBound as exc:
        assert str(exc).startswith("deny:destination_unbound")
    else:
        raise AssertionError("unbound scope unexpectedly resolved")


def test_outbound_origin_and_contract_gates():
    denied = map_entity(
        "d1", "decision", "D", {
            "classification": "public", "visibility": "public",
            "sync_origin": "onyx",
        }, "s", destination_policy=DestinationPolicy(
            classification_ceiling="public"
        ),
    )
    assert denied.skip_reason == "deny:origin_not_republishable"
    allowed = map_entity(
        "d1", "decision", "D", {
            "classification": "public", "visibility": "public",
        }, "s", destination_policy=DestinationPolicy(
            classification_ceiling="public"
        ),
    )
    assert allowed.skipped is False
    assert allowed.metadata["do_not_reimport"] is True


def test_safe_watermark_does_not_cross_unresolved_floor():
    assert _safe_watermark(
        ["2026-08-06T09:00:00Z", "2026-08-06T11:00:00Z"],
        ["2026-08-06T10:00:00Z"],
        "",
    ) == "2026-08-06T09:00:00Z"


class _SpyClient:
    def __init__(self):
        self.ingested: list[str] = []
        self.withdrawn: list[str] = []

    def ingest(self, document_id, **kwargs):
        self.ingested.append(document_id)
        return IngestResult(document_id, PushStatus.ACCEPTED, 200, attempts=1)

    def withdraw(self, document_id):
        self.withdrawn.append(document_id)
        return IngestResult(document_id, PushStatus.ACCEPTED, 200, attempts=1)


def test_tombstone_withdrawal_is_scope_bound_and_idempotent(tmp_path: Path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, "
        "properties TEXT, updated_at TEXT, scope_id TEXT, source_channel TEXT, version INTEGER)"
    )
    props = json.dumps({"classification": "public", "visibility": "public"})
    conn.execute(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1", "decision", "D", props, "2026-08-06", "s", "test", 1),
    )
    conn.commit()
    spy = _SpyClient()
    store = SyncStateStore(tmp_path / "sync.db")
    exporter = OnyxPushExporter(
        conn, spy, store,
        destination_policy=DestinationPolicy(
            classification_ceiling="public", supports_withdrawal=True
        ),
    )
    assert exporter.push_scope("s").pushed == 1
    conn.execute(
        "UPDATE entities SET properties=? WHERE id='e1'",
        (json.dumps({"classification": "public", "visibility": "public", "valid_to": "now"}),),
    )
    conn.commit()
    outcome = exporter.push_scope("s")
    assert outcome.withdrawn == 1
    assert len(spy.withdrawn) == 1
    assert exporter.push_scope("s").withdrawn == 0
    store.close()


def test_noop_state_is_withdrawn_after_tombstone(tmp_path: Path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, "
        "properties TEXT, updated_at TEXT, scope_id TEXT, source_channel TEXT, version INTEGER)"
    )
    conn.execute(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1", "decision", "D", json.dumps({
            "classification": "public", "visibility": "public",
        }), "2026-08-06", "s", "test", 1),
    )
    conn.commit()
    spy = _SpyClient()
    store = SyncStateStore(tmp_path / "sync.db")
    policy = DestinationPolicy(
        classification_ceiling="public", supports_withdrawal=True
    )
    exporter = OnyxPushExporter(conn, spy, store, destination_policy=policy)
    exporter.push_scope("s")
    assert exporter.push_scope("s").noop == 1
    conn.execute(
        "UPDATE entities SET properties=? WHERE id='e1'",
        (json.dumps({
            "classification": "public", "visibility": "public",
            "valid_to": "now",
        }),),
    )
    conn.commit()
    assert exporter.push_scope("s").withdrawn == 1
    assert len(spy.withdrawn) == 1
    store.close()


def test_dry_run_does_not_mark_noop(tmp_path: Path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, "
        "properties TEXT, updated_at TEXT, scope_id TEXT, source_channel TEXT, version INTEGER)"
    )
    conn.execute(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1", "decision", "D", json.dumps({
            "classification": "public", "visibility": "public",
        }), "2026-08-06", "s", "test", 1),
    )
    conn.commit()
    spy = _SpyClient()
    store = SyncStateStore(tmp_path / "sync.db")
    policy = DestinationPolicy(
        classification_ceiling="public", supports_withdrawal=True
    )
    exporter = OnyxPushExporter(conn, spy, store, destination_policy=policy)
    exporter.push_scope("s")
    document_id = "mnemosyne:s:decision:e1"
    assert store.get(document_id).status == "accepted"
    OnyxPushExporter(
        conn, None, store, dry_run=True, destination_policy=policy
    ).push_scope("s")
    assert store.get(document_id).status == "accepted"
    store.close()


def test_failed_live_state_is_withdrawn_after_tombstone(tmp_path: Path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, "
        "properties TEXT, updated_at TEXT, scope_id TEXT, source_channel TEXT, version INTEGER)"
    )
    conn.execute(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1", "decision", "D", json.dumps({
            "classification": "public", "visibility": "public",
        }), "2026-08-06", "s", "test", 1),
    )
    conn.commit()
    spy = _SpyClient()
    store = SyncStateStore(tmp_path / "sync.db")
    policy = DestinationPolicy(
        classification_ceiling="public", supports_withdrawal=True
    )
    exporter = OnyxPushExporter(conn, spy, store, destination_policy=policy)
    exporter.push_scope("s")
    store.mark_failed("mnemosyne:s:decision:e1", "transient")
    conn.execute(
        "UPDATE entities SET properties=? WHERE id='e1'",
        (json.dumps({
            "classification": "public", "visibility": "public",
            "valid_to": "now",
        }),),
    )
    conn.commit()
    assert exporter.push_scope("s").withdrawn == 1
    assert spy.withdrawn == ["mnemosyne:s:decision:e1"]
    store.close()
def test_default_public_ceiling_denies_private():
    mapped = map_entity(
        "e1", "decision", "D",
        {"classification": "private", "visibility": "public"},
        "s",
        destination_policy=DestinationPolicy(),
    )
    assert mapped.skipped is True
    assert mapped.skip_reason == "deny:classification_exceeds_destination"


def test_t60_exporter_constructor_type_hints_resolve():
    hints = get_type_hints(OnyxPushExporter.__init__)
    assert "kg_conn" in hints
    assert "sync_store" in hints

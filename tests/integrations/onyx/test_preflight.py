from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from mnemosyne.graph.knowledge_graph import KnowledgeGraph
from mnemosyne.integrations.onyx.config import OnyxEndpoint, SyncConfig, SyncPolicy
from mnemosyne.integrations.onyx.destinations import Destination
from mnemosyne.integrations.onyx.sync_state import PreflightRecord, SyncStateStore
from mnemosyne import cli as onyx_cli


def _destination(**overrides) -> Destination:
    values = {
        "destination_id": "dest-preflight",
        "base_url": "https://onyx.example.test",
        "api_key_env": "ONYX_TEST_KEY",
        "cc_pair_id_env": "ONYX_TEST_CC",
        "approved_hosts": ("onyx.example.test",),
    }
    values.update(overrides)
    return Destination(**values)


def _config(destination: Destination, ttl_hours: int = 24) -> SyncConfig:
    return SyncConfig(
        onyx=OnyxEndpoint(
            base_url=destination.base_url,
            api_key_env=destination.api_key_env,
            cc_pair_id_env=destination.cc_pair_id_env,
        ),
        destinations={destination.destination_id: destination},
        scope_bindings={"scope-a": destination.destination_id},
        sync=SyncPolicy(preflight_ttl_hours=ttl_hours),
    )


def _seed_entity(kg: KnowledgeGraph, *, entity_id: str = "e-1", private: bool = False):
    props = {
        "classification": "private" if private else "public",
        "visibility": "public",
        "outcome": "approved",
    }
    kg.conn.execute(
        "INSERT INTO entities (id, type, name, properties, created_at, updated_at, "
        "version, scope_id, source_channel) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (entity_id, "decision", "Synthetic title", json.dumps(props),
         "2026-08-06T00:00:00Z", "2026-08-06T00:00:00Z", 1, "scope-a", "test"),
    )
    kg.conn.commit()


def _args(tmp_path, *, dry_run: bool = False):
    return SimpleNamespace(
        db_path=str(tmp_path / "kg.db"),
        config="synthetic-config.yaml",
        scope_id="scope-a",
        dry_run=dry_run,
    )


def _record(store: SyncStateStore, destination: Destination, *, reviewed_at: str, deny_count: int = 0):
    store.record_preflight(PreflightRecord(
        scope_id="scope-a",
        destination_id=destination.destination_id,
        destination_fingerprint=destination.fingerprint(),
        reviewed_at=reviewed_at,
        actor="synthetic-reviewer",
        candidate_count=1,
        deny_count=deny_count,
    ))


def test_t36_live_push_without_preflight_denies_before_client_creation(monkeypatch, tmp_path):
    destination = _destination()
    cfg = _config(destination)
    monkeypatch.setattr(onyx_cli, "_load_sync_config", lambda _: cfg)
    with pytest.raises(ValueError, match="preflight_missing"):
        onyx_cli._run_sync_onyx_push(_args(tmp_path))
    assert not (tmp_path / "kg.db-wal").exists()


def test_t37_expired_preflight_record_is_denied(monkeypatch, tmp_path):
    destination = _destination()
    cfg = _config(destination)
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    store = SyncStateStore(kg.db_path)
    _record(store, destination, reviewed_at=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat())
    store.close()
    kg.close()
    monkeypatch.setattr(onyx_cli, "_load_sync_config", lambda _: cfg)
    with pytest.raises(ValueError, match="preflight_stale"):
        onyx_cli._run_sync_onyx_push(_args(tmp_path))


def test_t38_destination_fingerprint_change_denies_push(monkeypatch, tmp_path):
    reviewed_destination = _destination(classification_ceiling="public")
    changed_destination = _destination(classification_ceiling="internal")
    cfg = _config(changed_destination)
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    store = SyncStateStore(kg.db_path)
    _record(store, reviewed_destination, reviewed_at=datetime.now(timezone.utc).isoformat())
    store.close()
    kg.close()
    monkeypatch.setattr(onyx_cli, "_load_sync_config", lambda _: cfg)
    with pytest.raises(ValueError, match="preflight_destination_changed"):
        onyx_cli._run_sync_onyx_push(_args(tmp_path))


def test_t39_preflight_command_output_is_metadata_only(monkeypatch, tmp_path, capsys):
    destination = _destination()
    cfg = _config(destination)
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    _seed_entity(kg)
    kg.close()
    monkeypatch.setattr(onyx_cli, "_load_sync_config", lambda _: cfg)
    args = SimpleNamespace(
        db_path=str(tmp_path / "kg.db"),
        config="synthetic-config.yaml",
        scope_id="scope-a",
        actor="synthetic-reviewer",
    )
    onyx_cli._run_sync_onyx_preflight(args)
    output = capsys.readouterr().out
    assert "dest-preflight" in output
    assert "onyx.example.test" in output
    assert "CC_PAIR_ID_ENV" not in output
    assert "ONYX_TEST_CC" in output
    assert "Synthetic title" not in output
    assert "approved" not in output
    assert "external_uri" not in output


def test_t40_new_deny_after_preflight_stops_push(monkeypatch, tmp_path):
    destination = _destination()
    cfg = _config(destination)
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    _seed_entity(kg, private=True)
    store = SyncStateStore(kg.db_path)
    _record(store, destination, reviewed_at=datetime.now(timezone.utc).isoformat(), deny_count=0)
    store.close()
    kg.close()
    monkeypatch.setattr(onyx_cli, "_load_sync_config", lambda _: cfg)
    with pytest.raises(ValueError, match="preflight_stale"):
        onyx_cli._run_sync_onyx_push(_args(tmp_path))


def test_live_push_requires_recorded_operational_approval(monkeypatch, tmp_path):
    destination = _destination()
    cfg = _config(destination)
    kg = KnowledgeGraph(str(tmp_path / "kg.db"))
    _seed_entity(kg)
    store = SyncStateStore(kg.db_path)
    _record(store, destination, reviewed_at=datetime.now(timezone.utc).isoformat())
    store.close()
    kg.close()
    monkeypatch.setattr(onyx_cli, "_load_sync_config", lambda _: cfg)

    with pytest.raises(ValueError, match="operational_approval_missing"):
        onyx_cli._run_sync_onyx_push(_args(tmp_path))
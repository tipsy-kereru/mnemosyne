from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from mnemosyne.integrations.onyx.client import OnyxClient
from mnemosyne.integrations.onyx.exporter import OnyxPushExporter
from mnemosyne.integrations.onyx.mapper import (
    DestinationPolicy,
    map_entity,
)
from mnemosyne.integrations.onyx.sync_state import SyncStateStore

from datetime import datetime, timezone


def _fresh_acl() -> dict:
    return {
        "users": ["synthetic@example.test"],
        "groups": ["synthetic-group"],
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }




def test_t02_missing_classification_defaults_to_private_with_fresh_acl():
    props = _props()
    props.pop("classification")
    props["visibility"] = "private"
    props["access_snapshot"] = _fresh_acl()
    result = map_entity(
        "t02", "decision", "Synthetic", props, "scope-a",
        destination_policy=DestinationPolicy(
            classification_ceiling="private", supports_acl=True,
        ),
    )
    assert result.skipped is False
    assert result.metadata["classification"] == "private"


def test_t03_missing_visibility_defaults_to_private_with_fresh_acl():
    props = _props(classification="private")
    props.pop("visibility")
    props["access_snapshot"] = _fresh_acl()
    result = map_entity(
        "t03", "decision", "Synthetic", props, "scope-a",
        destination_policy=DestinationPolicy(
            classification_ceiling="private", supports_acl=True,
        ),
    )
    assert result.skipped is False
    assert result.metadata["visibility"] == "private"


def test_t04_classification_is_case_sensitive():
    result = map_entity(
        "t04", "decision", "Synthetic", _props(classification="Public"),
        "scope-a",
    )
    assert result.skip_reason == "deny:classification_unknown"




def test_t06_valid_to_alone_denies_mapping():
    result = map_entity(
        "t06", "decision", "Synthetic",
        _props(valid_to="2026-08-06T00:00:00Z"), "scope-a",
    )
    assert result.skip_reason == "deny:tombstoned"




def test_t08_mnemosyne_origin_is_not_republishable():
    result = map_entity(
        "t08", "decision", "Synthetic",
        _props(sync_origin="mnemosyne"), "scope-a",
    )
    assert result.skip_reason == "deny:origin_not_republishable"


def test_t09_sensitive_arbitrary_properties_never_reach_sections():
    result = map_entity(
        "t09", "decision", "Synthetic",
        _props(api_token="synthetic-token", note_body="private note",
               access_snapshot={"users": ["synthetic"]}), "scope-a",
    )
    text = result.sections[0]["text"]
    assert all(value not in text for value in ("synthetic-token", "private note", "synthetic"))


def test_t10_property_fuzz_keys_stay_outside_allowlisted_sections():
    props = _props(**{f"random_key_{index}": f"random_value_{index}" for index in range(100)})
    result = map_entity("t10", "decision", "Synthetic", props, "scope-a")
    text = result.sections[0]["text"]
    assert all(f"random_value_{index}" not in text for index in range(100))


def test_t11_classification_and_acl_changes_do_not_change_content_hash():
    first = map_entity(
        "t11", "decision", "Synthetic",
        _props(classification="public", access_snapshot=_fresh_acl()), "scope-a",
    )
    second = map_entity(
        "t11", "decision", "Synthetic",
        _props(classification="internal", access_snapshot={
            "users": ["other@example.test"], "captured_at": datetime.now(timezone.utc).isoformat(),
        }), "scope-a",
        destination_policy=DestinationPolicy(
            classification_ceiling="internal", supports_acl=True,
        ),
    )
    assert first.content_hash == second.content_hash




def test_t13_invalid_destination_ceiling_is_denied():
    result = map_entity(
        "t13", "decision", "Synthetic", _props(), "scope-a",
        destination_policy=DestinationPolicy(classification_ceiling="bogus"),
    )
    assert result.skip_reason == "deny:destination_ceiling_invalid"


def test_t14_acl_visibility_requires_destination_acl_capability():
    result = map_entity(
        "t14", "decision", "Synthetic",
        _props(visibility="project"), "scope-a",
    )
    assert result.skip_reason == "deny:destination_cannot_represent_acl"


def test_t15_stale_acl_snapshot_is_denied():
    result = map_entity(
        "t15", "decision", "Synthetic",
        _props(visibility="project", access_snapshot={
            "users": ["synthetic@example.test"],
            "captured_at": "2020-01-01T00:00:00+00:00",
        }), "scope-a",
        destination_policy=DestinationPolicy(supports_acl=True),
    )
    assert result.skip_reason == "deny:acl_snapshot_missing_or_stale"


def _props(**overrides):
    props = {"classification": "public", "visibility": "public", "outcome": "approved"}
    props.update(overrides)
    return props


def test_private_source_is_denied_for_public_destination():
    result = map_entity(
        "decision-1", "decision", "Decision", _props(classification="private"), "personal"
    )
    assert result.skipped is True
    assert "destination" in result.skip_reason


def test_tombstone_is_denied_at_mapping_boundary():
    result = map_entity(
        "decision-1", "decision", "Decision",
        _props(tombstoned_at="2026-08-05T00:00:00Z"), "personal",
    )
    assert result.skipped is True
    assert "tombston" in result.skip_reason


def test_section_text_uses_allowlist_not_arbitrary_properties():
    result = map_entity(
        "decision-1", "decision", "Decision",
        _props(api_token="redacted-value", note_body="private body"), "personal",
    )
    assert result.is_publishable is True
    text = result.sections[0]["text"]
    assert "redacted-value" not in text
    assert "private body" not in text
    assert "approved" in text


def test_exporter_excludes_tombstoned_rows_before_client_call(tmp_path: Path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, properties TEXT, "
        "updated_at TEXT, scope_id TEXT, source_channel TEXT, version INTEGER)"
    )
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("live", "decision", "Live", json.dumps(_props()), "2026-08-05", "s1", "cli", 1),
            ("dead", "decision", "Dead", json.dumps(_props(valid_to="2026-08-05")), "2026-08-05", "s1", "cli", 1),
        ],
    )
    conn.commit()
    store = SyncStateStore(tmp_path / "sync.db")
    exporter = OnyxPushExporter(conn, client=None, sync_store=store, dry_run=True)

    outcome = exporter.push_scope("s1")

    assert outcome.total == 1
    assert outcome.pushed == 1
    assert all("dead" not in str(detail) for detail in outcome.details)
    store.close()

def test_remote_http_destination_is_rejected():
    with pytest.raises(ValueError, match="https"):
        OnyxClient(
            base_url="http://example.invalid",
            api_key="test-key",
            cc_pair_id=1,
        )

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from mnemosyne.integrations.onyx.client import IngestResult, PushStatus
from mnemosyne.integrations.onyx.exporter import OnyxPushExporter
from mnemosyne.integrations.onyx.mapper import DestinationPolicy
from mnemosyne.integrations.onyx.sync_state import SyncStateStore


class SpyClient:
    def __init__(self):
        self.ingest_calls: list[str] = []
        self.withdraw_calls: list[str] = []

    def ingest(self, document_id, semantic_identifier, title, sections, metadata=None, doc_updated_at=None):
        self.ingest_calls.append(document_id)
        return IngestResult(document_id, PushStatus.ACCEPTED, status_code=200, attempts=1)

    def withdraw(self, document_id):
        self.withdraw_calls.append(document_id)
        return IngestResult(document_id, PushStatus.ACCEPTED, status_code=204, attempts=1)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, properties TEXT, "
        "updated_at TEXT, scope_id TEXT, source_channel TEXT, version INTEGER)"
    )
    conn.execute(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("entity-1", "decision", "Synthetic decision", json.dumps({
            "classification": "public", "visibility": "public", "outcome": "approved",
        }), "2026-08-06T00:00:00Z", "scope-a", "test", 1),
    )
    conn.commit()
    return conn


def _store(tmp_path: Path) -> SyncStateStore:
    return SyncStateStore(tmp_path / "sync.db")


def _policy(*, supports_withdrawal: bool, ceiling: str = "public") -> DestinationPolicy:
    return DestinationPolicy(
        destination_id="synthetic-destination",
        classification_ceiling=ceiling,
        supports_withdrawal=supports_withdrawal,
    )


def _publish(conn, store, client, *, policy=None):
    return OnyxPushExporter(
        conn, client, store, destination_policy=policy or _policy(supports_withdrawal=True)
    ).push_scope("scope-a")


def _tombstone(conn):
    row = conn.execute("SELECT properties FROM entities WHERE id='entity-1'").fetchone()
    props = json.loads(row["properties"])
    props["tombstoned_at"] = "2026-08-06T01:00:00Z"
    props["valid_to"] = props["tombstoned_at"]
    conn.execute("UPDATE entities SET properties=? WHERE id='entity-1'", (json.dumps(props),))
    conn.commit()


def _clear_tombstone(conn):
    row = conn.execute("SELECT properties FROM entities WHERE id='entity-1'").fetchone()
    props = json.loads(row["properties"])
    props.pop("tombstoned_at", None)
    props.pop("valid_to", None)
    conn.execute("UPDATE entities SET properties=? WHERE id='entity-1'", (json.dumps(props),))
    conn.commit()




def test_t21_unsupported_withdrawal_blocks_without_client_call(tmp_path):
    conn, store, first = _conn(), _store(tmp_path), SpyClient()
    _publish(conn, store, first)
    _tombstone(conn)
    second = SpyClient()
    outcome = _publish(conn, store, second, policy=_policy(supports_withdrawal=False))
    state = store.get("mnemosyne:scope-a:decision:entity-1")
    assert outcome.withdraw_blocked == 1
    assert second.withdraw_calls == []
    assert second.ingest_calls == []
    assert state.status == "withdraw_blocked"


def test_t22_blocked_withdrawal_retries_after_capability_enabled(tmp_path):
    conn, store, first = _conn(), _store(tmp_path), SpyClient()
    _publish(conn, store, first)
    _tombstone(conn)
    _publish(conn, store, SpyClient(), policy=_policy(supports_withdrawal=False))
    second = SpyClient()
    outcome = _publish(conn, store, second, policy=_policy(supports_withdrawal=True))
    assert outcome.withdrawn == 1
    assert second.withdraw_calls == ["mnemosyne:scope-a:decision:entity-1"]
    assert store.get("mnemosyne:scope-a:decision:entity-1").status == "withdrawn"




def test_t24_policy_denial_withdraws_previously_accepted_document(tmp_path):
    conn, store, first = _conn(), _store(tmp_path), SpyClient()
    conn.execute(
        "UPDATE entities SET properties=? WHERE id='entity-1'",
        (json.dumps({
            "classification": "private", "visibility": "public",
            "outcome": "approved",
        }),),
    )
    conn.commit()
    _publish(conn, store, first, policy=_policy(supports_withdrawal=True, ceiling="private"))
    second = SpyClient()
    outcome = _publish(conn, store, second, policy=_policy(supports_withdrawal=True, ceiling="public"))
    assert outcome.withdrawn == 1
    assert second.withdraw_calls == ["mnemosyne:scope-a:decision:entity-1"]
    assert any(detail.get("reason") == "withdraw:policy_denied" for detail in outcome.details)




def test_t26_reinstated_pending_state_can_be_accepted_again(tmp_path):
    conn, store, first = _conn(), _store(tmp_path), SpyClient()
    _publish(conn, store, first)
    state_id = "mnemosyne:scope-a:decision:entity-1"
    store.mark_withdrawn(state_id)
    _tombstone(conn)
    _clear_tombstone(conn)
    second = SpyClient()
    outcome = _publish(conn, store, second)
    assert outcome.pushed == 1
    assert second.ingest_calls == [state_id]
    assert store.get(state_id).status == "accepted"

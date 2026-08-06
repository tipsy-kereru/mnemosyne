"""Export Worker integration tests: Onyx → Mnemosyne (Phase 2).

Implements the §8 상태 전이 테스트 (state transition tests) for the
export direction:

- 신규 (new):        envelope → ingested (entity appears in KG)
- 동일 hash (noop):  second delivery with same content hash → noop
- 변경 (changed):    different content hash → new version ingested
- ACL 누락:          empty AccessSnapshot + require_snapshot → quarantined
- 검증 실패:         envelope with missing fields → rejected
- 삭제:              handle_deletion → entity tombstoned (not deleted)
- 배치:              checkpoint advances after a batch
- at-least-once:     re-delivering the same envelope is idempotent
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mnemosyne.integrations.onyx.acl import QuarantineRecord
from mnemosyne.integrations.onyx.checkpoint import CheckpointStore
from mnemosyne.integrations.onyx.config import (
    ConnectorMapping,
    SyncConfig,
)
from mnemosyne.integrations.onyx.contract import (
    AccessSnapshot,
    Envelope,
)
from mnemosyne.integrations.onyx.exporter import OnyxPushExporter
from mnemosyne.integrations.onyx.mapper import DestinationPolicy
from mnemosyne.integrations.onyx.sync_state import SyncStateStore
from mnemosyne.integrations.onyx.worker import (
    ExportWorker,
    ProcessResult,
    BatchResult,
)


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def kg_conn() -> sqlite3.Connection:
    """Minimal in-memory KG schema matching the knowledge graph."""
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
    conn.execute('''
        CREATE TABLE entity_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            properties TEXT,
            changed_at TEXT NOT NULL,
            change_type TEXT NOT NULL,
            version INTEGER
        )
    ''')
    conn.commit()
    return conn


@pytest.fixture
def checkpoint_store(tmp_path: Path) -> CheckpointStore:
    return CheckpointStore(tmp_path / "checkpoint_test.db")


def _config(acl_mode: str = "require_snapshot") -> SyncConfig:
    """A SyncConfig with one connector→scope mapping."""
    return SyncConfig(
        mappings=[
            ConnectorMapping(
                connector_id="connector-17",
                scope_id="client-a",
                source_channel="github",
                acl_mode=acl_mode,
            )
        ]
    )


@pytest.fixture
def worker(
    kg_conn: sqlite3.Connection,
    checkpoint_store: CheckpointStore,
) -> ExportWorker:
    return ExportWorker(kg_conn, checkpoint_store, _config())


# ── Envelope builders ───────────────────────────────────────────────

def _fresh_snapshot() -> AccessSnapshot:
    return AccessSnapshot(
        users=["alice@example.com"],
        groups=["project-client-a"],
        captured_at=datetime.now(timezone.utc).isoformat(),
    )


def _envelope(**overrides) -> Envelope:
    """A well-formed, valid Envelope with a fresh ACL snapshot."""
    base = dict(
        source_system="onyx",
        source_type="github",
        onyx_connector_id="connector-17",
        onyx_cc_pair_id=243,
        external_document_id="github:acme/widgets:issue:193",
        external_revision="rev-1",
        external_uri="https://github.com/acme/widgets/issues/193",
        title="인증 방식 결정",
        sections=[{"text": "OAuth 2.0 with PKCE를 사용하기로 결정했다."}],
        source_updated_at="2026-08-02T10:20:00Z",
        scope_id="client-a",
        source_channel="github",
        classification="internal",
        access_snapshot=_fresh_snapshot(),
    )
    base.update(overrides)
    return Envelope(**base)


def _count_entities(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]


def _entity(conn: sqlite3.Connection, entity_id: str) -> sqlite3.Row:
    return conn.execute(
        "SELECT * FROM entities WHERE id = ?", (entity_id,)
    ).fetchone()


def _props(row: sqlite3.Row) -> dict:
    return json.loads(row["properties"])


# ── Tests ───────────────────────────────────────────────────────────

class TestNewDocument:
    """신규: Discovered → Fetched → Ingested."""

    def test_new_envelope_is_ingested(self, worker: ExportWorker):
        env = _envelope()
        result = worker.process_envelope(env)

        assert result.status == "ingested"
        assert result.entity_id != ""
        assert result.content_hash == env.content_hash
        assert result.skipped is False

    def test_entity_appears_in_kg(self, worker: ExportWorker, kg_conn):
        env = _envelope()
        result = worker.process_envelope(env)

        row = _entity(kg_conn, result.entity_id)
        assert row is not None
        assert row["type"] == "github"          # from source_type
        assert row["name"] == env.title
        assert row["scope_id"] == "client-a"
        assert row["source_channel"] == "onyx"
        assert row["version"] == 1

        props = _props(row)
        assert props["source_doc_id"] == env.source_doc_id
        assert props["external_uri"] == env.external_uri
        assert props["content_hash"] == env.content_hash

    def test_history_records_creation(self, worker: ExportWorker, kg_conn):
        env = _envelope()
        result = worker.process_envelope(env)

        rows = kg_conn.execute(
            "SELECT * FROM entity_history WHERE entity_id = ?",
            (result.entity_id,),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["change_type"] == "created"
        assert rows[0]["version"] == 1


class TestIdempotency:
    """동일 content_hash: second delivery → noop (no duplicate)."""

    def test_same_hash_is_noop(self, worker: ExportWorker, kg_conn):
        env = _envelope()
        first = worker.process_envelope(env)
        assert first.status == "ingested"

        second = worker.process_envelope(env)
        assert second.status == "noop"
        assert second.entity_id == first.entity_id
        assert second.skipped is True

        # No duplicate entity created.
        assert _count_entities(kg_conn) == 1

    def test_at_least_once_redelivery_is_idempotent(
        self, worker: ExportWorker, kg_conn
    ):
        env = _envelope()
        # Simulate at-least-once delivery: the same envelope arrives 3×.
        results = [worker.process_envelope(env) for _ in range(3)]

        assert [r.status for r in results] == ["ingested", "noop", "noop"]
        assert _count_entities(kg_conn) == 1
        # One created history row; no spurious updates.
        history = kg_conn.execute(
            "SELECT change_type FROM entity_history"
        ).fetchall()
        assert [r["change_type"] for r in history] == ["created"]


class TestChangedContent:
    """변경: ActiveVersion → ChangedContent → NewVersion."""

    def test_changed_content_creates_new_version(
        self, worker: ExportWorker, kg_conn
    ):
        env_v1 = _envelope()
        r1 = worker.process_envelope(env_v1)
        assert r1.status == "ingested"

        # Same document identity, changed body → new content hash.
        env_v2 = _envelope(
            external_revision="rev-2",
            sections=[{"text": "SAML SSO로 결정을 변경했다."}],
            source_updated_at="2026-08-02T11:00:00Z",
        )
        assert env_v2.content_hash != env_v1.content_hash

        r2 = worker.process_envelope(env_v2)
        assert r2.status == "ingested"
        # Same entity (stable identity), bumped version.
        assert r2.entity_id == r1.entity_id

        row = _entity(kg_conn, r2.entity_id)
        assert row["version"] == 2
        props = _props(row)
        assert props["content_hash"] == env_v2.content_hash
        assert props["external_revision"] == "rev-2"

        # History now records created + updated.
        history = kg_conn.execute(
            "SELECT change_type, version FROM entity_history "
            "WHERE entity_id = ? ORDER BY id",
            (r2.entity_id,),
        ).fetchall()
        assert [(r["change_type"], r["version"]) for r in history] == [
            ("created", 1),
            ("updated", 2),
        ]


class TestQuarantine:
    """ACL 누락: Fetched → Quarantined."""

    def test_empty_acl_with_require_snapshot_is_quarantined(
        self, worker: ExportWorker, kg_conn
    ):
        env = _envelope(access_snapshot=AccessSnapshot())
        assert env.access_snapshot.is_empty()

        result = worker.process_envelope(env)
        assert result.status == "quarantined"
        assert result.skipped is True
        assert "ACL" in result.error or "snapshot" in result.error

        # Nothing ingested.
        assert _count_entities(kg_conn) == 0

        # Quarantine record persisted.
        q = kg_conn.execute(
            "SELECT * FROM onyx_quarantine WHERE source_doc_id = ?",
            (env.source_doc_id,),
        ).fetchone()
        assert q is not None
        assert q["resolved"] == 0

    def test_fresh_acl_is_not_quarantined(self, worker: ExportWorker):
        env = _envelope(access_snapshot=_fresh_snapshot())
        result = worker.process_envelope(env)
        assert result.status == "ingested"

    def test_no_mapping_quarantines(self, kg_conn, checkpoint_store):
        # A connector with no mapping in config → quarantine.
        cfg = SyncConfig(mappings=[])
        w = ExportWorker(kg_conn, checkpoint_store, cfg)
        env = _envelope(access_snapshot=_fresh_snapshot())

        result = w.process_envelope(env)
        assert result.status == "quarantined"
        assert "mapping" in result.error


class TestValidation:
    """검증 실패: malformed envelope → rejected."""

    def test_missing_title_is_rejected(self, worker: ExportWorker, kg_conn):
        env = _envelope(title="   ")
        result = worker.process_envelope(env)

        assert result.status == "rejected"
        assert result.skipped is True
        assert result.error != ""
        assert _count_entities(kg_conn) == 0

    def test_missing_external_document_id_is_rejected(
        self, worker: ExportWorker
    ):
        env = _envelope(external_document_id="")
        result = worker.process_envelope(env)
        assert result.status == "rejected"

    def test_missing_connector_id_for_onyx_is_rejected(
        self, worker: ExportWorker
    ):
        env = _envelope(onyx_connector_id="")
        result = worker.process_envelope(env)
        assert result.status == "rejected"
        assert "onyx_connector_id" in result.error


class TestDeletion:
    """삭제: SourceWithdrawn → TombstoneWritten → HistoricalOnly."""

    def test_handle_deletion_tombstones_entity(
        self, worker: ExportWorker, kg_conn
    ):
        env = _envelope()
        result = worker.process_envelope(env)
        entity_id = result.entity_id

        outcome = worker.handle_deletion(env.source_doc_id, env.scope_id)
        assert outcome == "tombstoned"

        # Row still exists (never physically deleted).
        row = _entity(kg_conn, entity_id)
        assert row is not None
        props = _props(row)
        assert "tombstoned_at" in props
        assert "valid_to" in props
        assert props["valid_to"] == props["tombstoned_at"]

        # Deletion recorded in history.
        deleted = kg_conn.execute(
            "SELECT * FROM entity_history "
            "WHERE entity_id = ? AND change_type = 'deleted'",
            (entity_id,),
        ).fetchall()
        assert len(deleted) == 1

    def test_handle_deletion_not_found(self, worker: ExportWorker):
        outcome = worker.handle_deletion("onyx:connector-17:nope", "client-a")
        assert outcome == "not_found"


class TestBatchAndCheckpoint:
    """배치: checkpoint advances after a batch."""

    def test_batch_processes_and_advances_checkpoint(
        self, worker: ExportWorker, checkpoint_store: CheckpointStore
    ):
        connector_id = "connector-17"
        envelopes = [
            _envelope(
                external_document_id="github:doc:1",
                source_updated_at="2026-08-02T10:00:00Z",
            ),
            _envelope(
                external_document_id="github:doc:2",
                source_updated_at="2026-08-02T11:00:00Z",
            ),
            _envelope(
                external_document_id="github:doc:3",
                source_updated_at="2026-08-02T09:00:00Z",
            ),
        ]

        result = worker.process_batch(envelopes, connector_id)

        assert isinstance(result, BatchResult)
        assert result.total == 3
        assert result.ingested == 3
        assert result.failed == 0
        # Watermark = latest timestamp seen.
        assert result.checkpoint_watermark == "2026-08-02T11:00:00Z"

        cp = checkpoint_store.get(connector_id)
        assert cp is not None
        assert cp.scope_id == "client-a"
        assert cp.last_watermark == "2026-08-02T11:00:00Z"
        assert cp.documents_processed == 3
        assert cp.last_error == ""

    def test_batch_with_noop_and_reject_counts(
        self, worker: ExportWorker, checkpoint_store: CheckpointStore
    ):
        connector_id = "connector-17"
        good = _envelope(external_document_id="github:doc:good")
        duplicate = _envelope(external_document_id="github:doc:good")
        bad = _envelope(
            external_document_id="github:doc:bad", title=""
        )

        result = worker.process_batch([good, duplicate, bad], connector_id)

        assert result.total == 3
        assert result.ingested == 1
        assert result.noop == 1
        assert result.rejected == 1

    def test_batch_resume_advances_watermark(
        self, worker: ExportWorker, checkpoint_store: CheckpointStore
    ):
        connector_id = "connector-17"

        first = worker.process_batch(
            [_envelope(
                external_document_id="github:doc:1",
                source_updated_at="2026-08-02T10:00:00Z",
            )],
            connector_id,
        )
        assert first.checkpoint_watermark == "2026-08-02T10:00:00Z"
        assert checkpoint_store.get(connector_id).documents_processed == 1

        second = worker.process_batch(
            [_envelope(
                external_document_id="github:doc:2",
                source_updated_at="2026-08-02T12:00:00Z",
            )],
            connector_id,
        )
        assert second.checkpoint_watermark == "2026-08-02T12:00:00Z"
        # Cumulative processed count.
        assert checkpoint_store.get(connector_id).documents_processed == 2


class TestDefaultEntityType:
    def test_envelope_without_source_type_uses_document_fallback(
        self, worker: ExportWorker, kg_conn
    ):
        env = _envelope(source_type="")
        result = worker.process_envelope(env)
        assert result.status == "ingested"

        row = _entity(kg_conn, result.entity_id)
        assert row["type"] == "document"
class TestLifecycleSafety:
    def test_same_hash_with_stale_acl_is_quarantined(self, worker: ExportWorker):
        env = _envelope()
        assert worker.process_envelope(env).status == "ingested"

        stale = _envelope(
            access_snapshot=AccessSnapshot(
                users=["alice@example.com"],
                groups=["project-client-a"],
                captured_at="2020-01-01T00:00:00+00:00",
            )
        )
        assert worker.process_envelope(stale).status == "quarantined"

    def test_quarantine_does_not_advance_checkpoint(
        self, worker: ExportWorker, checkpoint_store: CheckpointStore
    ):
        result = worker.process_batch(
            [
                _envelope(
                    external_document_id="github:blocked",
                    source_updated_at="2026-08-02T13:00:00Z",
                    access_snapshot=AccessSnapshot(),
                )
            ],
            "connector-17",
        )

        assert result.quarantined == 1
        assert result.checkpoint_watermark == ""
        checkpoint = checkpoint_store.get("connector-17")
        assert checkpoint is not None
        assert checkpoint.last_watermark == ""
        assert checkpoint.last_error

    def test_deletion_is_scope_bound_and_idempotent(
        self, worker: ExportWorker, kg_conn
    ):
        env = _envelope()
        entity_id = worker.process_envelope(env).entity_id

        assert worker.handle_deletion(env.source_doc_id, "client-b") == "not_found"
        assert worker.handle_deletion(env.source_doc_id, env.scope_id) == "tombstoned"
        assert worker.handle_deletion(env.source_doc_id, env.scope_id) == "tombstoned_noop"

        deleted = kg_conn.execute(
            "SELECT COUNT(*) AS n FROM entity_history "
            "WHERE entity_id = ? AND change_type = 'deleted'",
            (entity_id,),
        ).fetchone()["n"]
        assert deleted == 1

    def test_tombstoned_entity_cannot_reactivate_on_update(
        self, worker: ExportWorker
    ):
        env = _envelope()
        worker.process_envelope(env)
        assert worker.handle_deletion(env.source_doc_id, env.scope_id) == "tombstoned"

        changed = _envelope(
            external_revision="rev-2",
            sections=[{"text": "changed after withdrawal"}],
        )
        result = worker.process_envelope(changed)
        assert result.status == "rejected"
        assert "reinstatement" in result.error
        assert result.entity_id == ""



def test_reinstate_records_auditable_history(
    worker: ExportWorker, kg_conn: sqlite3.Connection
):
    env = _envelope()
    entity_id = worker.process_envelope(env).entity_id
    assert worker.handle_deletion(env.source_doc_id, env.scope_id) == "tombstoned"
    assert worker.reinstate(
        env.source_doc_id, env.scope_id, actor="reviewer",
        reason="deletion was accidental",
    ) == "reinstated"
    row = kg_conn.execute(
        "SELECT properties FROM entity_history "
        "WHERE entity_id=? AND change_type='reinstated'",
        (entity_id,),
    ).fetchone()
    assert row is not None
    history = json.loads(row["properties"])
    assert history["reinstated_by"] == "reviewer"
    assert history["reinstated_reason"] == "deletion was accidental"


def test_quarantine_key_is_composite_and_preserves_legacy_record(
    kg_conn: sqlite3.Connection, checkpoint_store: CheckpointStore
):
    kg_conn.execute('''
        CREATE TABLE onyx_quarantine (
            source_doc_id TEXT PRIMARY KEY,
            scope_id TEXT,
            reason TEXT,
            quarantined_at TEXT,
            envelope_snapshot TEXT,
            resolved INTEGER DEFAULT 0,
            resolved_at TEXT,
            resolution TEXT
        )
    ''')
    kg_conn.execute(
        "INSERT INTO onyx_quarantine VALUES (?, ?, ?, ?, ?, 0, NULL, NULL)",
        ("same-source", "scope-a", "legacy", "2026-08-06", "{}"),
    )
    kg_conn.commit()
    worker = ExportWorker(kg_conn, checkpoint_store, _config())
    worker._store_quarantine(QuarantineRecord(
        source_doc_id="same-source", scope_id="scope-b", reason="new",
        envelope_snapshot={},
    ))
    rows = kg_conn.execute(
        "SELECT source_doc_id, scope_id, reason FROM onyx_quarantine "
        "ORDER BY scope_id"
    ).fetchall()
    assert [(row["source_doc_id"], row["scope_id"], row["reason"])
            for row in rows] == [
        ("same-source", "scope-a", "legacy"),
        ("same-source", "scope-b", "new"),
    ]


def test_t41_stale_acl_on_same_hash_is_quarantined_not_noop(worker: ExportWorker):
    env = _envelope()
    assert worker.process_envelope(env).status == "ingested"
    stale = _envelope(
        access_snapshot=AccessSnapshot(
            users=["alice@example.com"], groups=["project-client-a"],
            captured_at="2020-01-01T00:00:00+00:00",
        )
    )
    result = worker.process_envelope(stale)
    assert result.status == "quarantined"
    assert result.status != "noop"


def test_t42_quarantine_at_earlier_timestamp_holds_watermark(
    worker: ExportWorker, checkpoint_store: CheckpointStore
):
    result = worker.process_batch(
        [
            _envelope(
                external_document_id="github:blocked",
                source_updated_at="2026-08-02T10:00:00Z",
                access_snapshot=AccessSnapshot(),
            ),
            _envelope(
                external_document_id="github:accepted",
                source_updated_at="2026-08-02T11:00:00Z",
            ),
        ],
        "connector-17",
    )
    assert result.quarantined == 1
    assert result.ingested == 1
    assert result.checkpoint_watermark == ""
    assert checkpoint_store.get("connector-17").last_watermark == ""


def test_t43_all_failed_batch_keeps_watermark_and_records_error(
    worker: ExportWorker, checkpoint_store: CheckpointStore, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(worker, "_upsert_entity", fail)
    result = worker.process_batch(
        [_envelope(source_updated_at="2026-08-02T10:00:00Z")], "connector-17"
    )
    checkpoint = checkpoint_store.get("connector-17")
    assert result.failed == 1
    assert result.checkpoint_watermark == ""
    assert checkpoint.last_watermark == ""
    assert checkpoint.last_error


def test_t44_success_after_failed_batch_clears_error_and_advances(
    worker: ExportWorker, checkpoint_store: CheckpointStore, monkeypatch
):
    original = worker._upsert_entity
    monkeypatch.setattr(worker, "_upsert_entity", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic")))
    worker.process_batch(
        [_envelope(source_updated_at="2026-08-02T10:00:00Z")], "connector-17"
    )
    monkeypatch.setattr(worker, "_upsert_entity", original)
    result = worker.process_batch(
        [_envelope(
            external_document_id="github:recovered",
            source_updated_at="2026-08-02T11:00:00Z",
        )],
        "connector-17",
    )
    checkpoint = checkpoint_store.get("connector-17")
    assert result.ingested == 1
    assert checkpoint.last_watermark == "2026-08-02T11:00:00Z"
    assert checkpoint.last_error == ""


def test_t45_decision_source_type_falls_back_to_document(worker: ExportWorker, kg_conn):
    result = worker.process_envelope(_envelope(source_type="decision"))
    assert result.status == "ingested"
    row = _entity(kg_conn, result.entity_id)
    assert row["type"] == "document"


def test_t46_invalid_source_types_use_document_fallback(worker: ExportWorker, kg_conn):
    for index, source_type in enumerate(("", "../../etc", "Decision")):
        result = worker.process_envelope(
            _envelope(source_type=source_type, external_document_id=f"github:invalid:{index}")
        )
        assert result.status == "ingested"
        assert _entity(kg_conn, result.entity_id)["type"] == "document"


def test_t47_nonpublishable_fallback_is_not_sent_to_push_scope(
    worker: ExportWorker, kg_conn, tmp_path: Path
):
    result = worker.process_envelope(_envelope(source_type="decision"))
    store = SyncStateStore(tmp_path / "sync.db")
    exporter = OnyxPushExporter(
        kg_conn, None, store, dry_run=True, destination_policy=DestinationPolicy()
    )
    outcome = exporter.push_scope("client-a")
    assert outcome.pushed == 0
    assert outcome.skipped == 1


def test_t48_replay_runs_validation_and_acl_again(worker: ExportWorker, monkeypatch):
    import mnemosyne.integrations.onyx.worker as worker_module

    validate_calls = 0
    acl_calls = 0
    original_validate = worker_module.validate_envelope
    original_acl = worker_module.should_quarantine

    def validate_spy(envelope):
        nonlocal validate_calls
        validate_calls += 1
        return original_validate(envelope)

    def acl_spy(envelope, mapping):
        nonlocal acl_calls
        acl_calls += 1
        return original_acl(envelope, mapping)

    monkeypatch.setattr(worker_module, "validate_envelope", validate_spy)
    monkeypatch.setattr(worker_module, "should_quarantine", acl_spy)
    env = _envelope(access_snapshot=AccessSnapshot())
    assert worker.process_envelope(env).status == "quarantined"
    result = worker.resolve_quarantine(
        env.source_doc_id, env.scope_id, actor="reviewer",
        decision="replay",
    )
    assert result == "quarantined"
    assert validate_calls == 2
    assert acl_calls == 2


def test_t49_rejecting_quarantine_preserves_record_without_entity(
    worker: ExportWorker, kg_conn
):
    env = _envelope(access_snapshot=AccessSnapshot())
    assert worker.process_envelope(env).status == "quarantined"
    assert worker.resolve_quarantine(
        env.source_doc_id, env.scope_id, actor="reviewer",
        decision="reject", reason="synthetic review",
    ) == "rejected"
    record = kg_conn.execute(
        "SELECT resolved, resolution FROM onyx_quarantine WHERE source_doc_id=? AND scope_id=?",
        (env.source_doc_id, env.scope_id),
    ).fetchone()
    assert tuple(record) == (1, "rejected")
    assert _count_entities(kg_conn) == 0


def test_t50_empty_actor_cannot_resolve_quarantine(worker: ExportWorker):
    env = _envelope(access_snapshot=AccessSnapshot())
    worker.process_envelope(env)
    assert worker.resolve_quarantine(
        env.source_doc_id, env.scope_id, actor="", decision="reject"
    ) == "reject:replay_unauthorized"


def test_t51_deletion_with_wrong_scope_does_not_tombstone(worker: ExportWorker, kg_conn):
    env = _envelope()
    worker.process_envelope(env)
    assert worker.handle_deletion(env.source_doc_id, "other-scope") == "not_found"
    source = kg_conn.execute(
        "SELECT entity_id FROM onyx_source_index WHERE source_doc_id=? AND scope_id=?",
        (env.source_doc_id, env.scope_id),
    ).fetchone()
    assert "tombstoned_at" not in _props(_entity(kg_conn, source["entity_id"]))


def test_t52_repeated_deletion_has_one_history_row(worker: ExportWorker, kg_conn):
    env = _envelope()
    entity_id = worker.process_envelope(env).entity_id
    assert worker.handle_deletion(env.source_doc_id, env.scope_id) == "tombstoned"
    assert worker.handle_deletion(env.source_doc_id, env.scope_id) == "tombstoned_noop"
    count = kg_conn.execute(
        "SELECT COUNT(*) AS n FROM entity_history WHERE entity_id=? AND change_type='deleted'",
        (entity_id,),
    ).fetchone()["n"]
    assert count == 1


def test_t53_tombstoned_source_rejects_content_change(worker: ExportWorker):
    env = _envelope()
    worker.process_envelope(env)
    worker.handle_deletion(env.source_doc_id, env.scope_id)
    result = worker.process_envelope(
        _envelope(external_revision="rev-2", sections=[{"text": "changed"}])
    )
    assert result.status == "rejected"
    assert result.error.startswith("reject:tombstoned_source")


def test_t54_reinstate_clears_tombstone_and_records_actor_reason(
    worker: ExportWorker, kg_conn
):
    env = _envelope()
    entity_id = worker.process_envelope(env).entity_id
    worker.handle_deletion(env.source_doc_id, env.scope_id)
    assert worker.reinstate(
        env.source_doc_id, env.scope_id, actor="reviewer", reason="synthetic correction"
    ) == "reinstated"
    row = _entity(kg_conn, entity_id)
    props = _props(row)
    assert "tombstoned_at" not in props
    assert "valid_to" not in props
    history = kg_conn.execute(
        "SELECT properties FROM entity_history WHERE entity_id=? AND change_type='reinstated'",
        (entity_id,),
    ).fetchone()
    restored = json.loads(history["properties"])
    assert restored["reinstated_by"] == "reviewer"
    assert restored["reinstated_reason"] == "synthetic correction"


def test_t55_source_index_keeps_same_document_in_two_scopes(
    kg_conn, checkpoint_store
):
    config_a = _config()
    first = ExportWorker(kg_conn, checkpoint_store, config_a)
    env_a = _envelope()
    first.process_envelope(env_a)
    config_b = SyncConfig(mappings=[ConnectorMapping(
        connector_id="connector-17", scope_id="scope-b", source_channel="github"
    )])
    second = ExportWorker(kg_conn, checkpoint_store, config_b)
    env_b = _envelope(scope_id="scope-b")
    second.process_envelope(env_b)
    rows = kg_conn.execute(
        "SELECT source_doc_id, scope_id FROM onyx_source_index WHERE source_doc_id=? ORDER BY scope_id",
        (env_a.source_doc_id,),
    ).fetchall()
    assert [(row["source_doc_id"], row["scope_id"]) for row in rows] == [
        (env_a.source_doc_id, "client-a"),
        (env_a.source_doc_id, "scope-b"),
    ]


def test_t59_mapping_classification_floor_overrides_public_envelope(
    worker: ExportWorker, kg_conn
):
    env = _envelope(classification="public")
    result = worker.process_envelope(env)
    assert result.status == "ingested"
    assert _props(_entity(kg_conn, result.entity_id))["classification"] == "internal"
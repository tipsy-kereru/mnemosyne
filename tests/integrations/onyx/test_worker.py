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

from mnemosyne.integrations.onyx.checkpoint import CheckpointStore
from mnemosyne.integrations.onyx.config import (
    ConnectorMapping,
    SyncConfig,
)
from mnemosyne.integrations.onyx.contract import (
    AccessSnapshot,
    Envelope,
)
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

"""Export Worker: Onyx common Document → Mnemosyne ingestion.

Receives :class:`Envelope` objects from Onyx's common Document stage and
ingests them into the knowledge graph. This is the *reverse* direction
of :mod:`exporter` (which pushes curated Mnemosyne knowledge → Onyx).

Implements the §6 Phase 2 principles:

- Per-connector checkpoint and watermark (``CheckpointStore``).
- At-least-once delivery with idempotent ingestion (§3 rule 2: same
  content hash is a no-op).
- ACL-unverifiable documents are quarantined, never auto-promoted
  (§3 rule 7).
- Source deletion becomes a tombstone (``tombstoned_at`` / ``valid_to``)
  — the entity row is never physically deleted (§3 rule 5).
- Changed content produces a new version; the old version is retained in
  ``entity_history`` (§3 rule 3).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from mnemosyne.integrations.onyx.acl import (
    QuarantineRecord,
    create_quarantine,
    should_quarantine,
)
from mnemosyne.integrations.onyx.checkpoint import CheckpointStore
from mnemosyne.integrations.onyx.config import ConnectorMapping, SyncConfig
from mnemosyne.integrations.onyx.contract import (
    Envelope,
    entity_stable_id,
    validate_envelope,
)

logger = logging.getLogger(__name__)

# Ingest lifecycle statuses (§4 state machine, export direction).
STATUS_INGESTED = "ingested"
STATUS_NOOP = "noop"
STATUS_QUARANTINED = "quarantined"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"

# Entity type used when an envelope carries no source_type.
_DEFAULT_ENTITY_TYPE = "document"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProcessResult:
    """Outcome of processing a single Envelope."""

    status: str
    entity_id: str = ""
    content_hash: str = ""
    error: str = ""
    skipped: bool = False


@dataclass
class BatchResult:
    """Aggregate outcome of processing a batch of Envelopes."""

    connector_id: str
    total: int = 0
    ingested: int = 0
    noop: int = 0
    quarantined: int = 0
    rejected: int = 0
    failed: int = 0
    checkpoint_watermark: str = ""


class ExportWorker:
    """Ingests Onyx-sourced Envelopes into the Mnemosyne KG.

    Args:
        kg_conn: Open SQLite connection to the knowledge graph.
        checkpoint_store: :class:`CheckpointStore` for per-connector
            watermark tracking.
        config: :class:`SyncConfig` providing connector→scope mappings
            and ACL policy.
    """

    def __init__(
        self,
        kg_conn: sqlite3.Connection,
        checkpoint_store: CheckpointStore,
        config: SyncConfig,
    ) -> None:
        self.conn = kg_conn
        self.checkpoint_store = checkpoint_store
        self.config = config
        self._init_tables()

    # ── Schema ────────────────────────────────────────────────────

    def _init_tables(self) -> None:
        """Idempotently create the worker-owned tables in the KG DB.

        - ``onyx_source_index``: idempotency / provenance index keyed by
          the stable Onyx source document ID.
        - ``onyx_quarantine``: persisted quarantine records (§4).

        The ``entities`` and ``entity_history`` tables are owned by the
        knowledge graph and assumed to already exist.
        """
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS onyx_source_index (
                source_doc_id  TEXT PRIMARY KEY,
                scope_id       TEXT NOT NULL,
                content_hash   TEXT NOT NULL,
                entity_id      TEXT NOT NULL,
                version        INTEGER NOT NULL DEFAULT 1,
                ingested_at    TEXT NOT NULL
            )
        ''')
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_onyx_source_scope "
            "ON onyx_source_index(scope_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_onyx_source_entity "
            "ON onyx_source_index(entity_id)"
        )
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS onyx_quarantine (
                source_doc_id     TEXT PRIMARY KEY,
                scope_id          TEXT NOT NULL,
                reason            TEXT NOT NULL,
                quarantined_at    TEXT NOT NULL,
                envelope_snapshot TEXT,
                resolved          INTEGER NOT NULL DEFAULT 0,
                resolved_at       TEXT,
                resolution        TEXT
            )
        ''')
        self.conn.commit()

    # ── Single-envelope processing ────────────────────────────────

    def process_envelope(self, envelope: Envelope) -> ProcessResult:
        """Process one document through the export pipeline.

        Order follows the §4 state machine:

        1. **Validate** — contract violations → ``rejected``.
        2. **Idempotency** — same content hash already ingested → ``noop``.
        3. **ACL quarantine** — unverifiable access → ``quarantined``.
        4. **Ingest** — upsert the entity into the KG → ``ingested``.
        """
        # 1. Validate against the data contract.
        errors = validate_envelope(envelope)
        if errors:
            logger.warning(
                "Envelope rejected (external_document_id=%s): %s",
                envelope.external_document_id,
                "; ".join(errors),
            )
            return ProcessResult(
                status=STATUS_REJECTED,
                content_hash=envelope.content_hash,
                error="; ".join(errors),
                skipped=True,
            )

        # 2. Idempotency: same source + same content hash = no-op.
        existing = self._lookup_source(envelope.source_doc_id)
        if (
            existing is not None
            and existing["content_hash"] == envelope.content_hash
        ):
            logger.debug(
                "No-op: source_doc_id=%s already ingested with same hash",
                envelope.source_doc_id,
            )
            return ProcessResult(
                status=STATUS_NOOP,
                entity_id=existing["entity_id"],
                content_hash=envelope.content_hash,
                skipped=True,
            )

        # 3. ACL quarantine.
        mapping = self.config.mapping_for_connector(
            envelope.onyx_connector_id
        )
        quarantined, reason = should_quarantine(envelope, mapping)
        if quarantined:
            record = create_quarantine(envelope, reason)
            self._store_quarantine(record)
            logger.info(
                "Envelope quarantined (source_doc_id=%s): %s",
                envelope.source_doc_id,
                reason,
            )
            return ProcessResult(
                status=STATUS_QUARANTINED,
                content_hash=envelope.content_hash,
                error=reason,
                skipped=True,
            )

        # 4. Ingest.
        try:
            entity_id = self._upsert_entity(envelope, existing)
        except Exception as exc:  # noqa: BLE001 - surface as failed status
            logger.exception(
                "Ingest failed for source_doc_id=%s", envelope.source_doc_id
            )
            return ProcessResult(
                status=STATUS_FAILED,
                content_hash=envelope.content_hash,
                error=str(exc),
            )

        return ProcessResult(
            status=STATUS_INGESTED,
            entity_id=entity_id,
            content_hash=envelope.content_hash,
        )

    # ── Batch processing ──────────────────────────────────────────

    def process_batch(
        self,
        envelopes: list[Envelope],
        connector_id: str,
    ) -> BatchResult:
        """Process a batch, then advance the connector checkpoint.

        Each envelope is processed independently; a failure on one does
        not abort the rest (at-least-once with idempotent re-tries).
        """
        result = BatchResult(connector_id=connector_id)
        watermark = ""
        scope_id = ""

        for env in envelopes:
            result.total += 1
            if not scope_id:
                scope_id = env.scope_id

            pr = self.process_envelope(env)
            if pr.status == STATUS_INGESTED:
                result.ingested += 1
            elif pr.status == STATUS_NOOP:
                result.noop += 1
            elif pr.status == STATUS_QUARANTINED:
                result.quarantined += 1
            elif pr.status == STATUS_REJECTED:
                result.rejected += 1
            elif pr.status == STATUS_FAILED:
                result.failed += 1
                self.checkpoint_store.record_error(connector_id, pr.error)

            # Watermark = the latest source timestamp seen (ISO-sortable).
            candidate = env.source_updated_at or env.captured_at
            if candidate and candidate > watermark:
                watermark = candidate

        # Resolve scope from the mapping when envelopes were empty/blank.
        if not scope_id:
            mapping = self.config.mapping_for_connector(connector_id)
            scope_id = mapping.scope_id if mapping else ""

        # Advance checkpoint (§6 Phase 2: resume from watermark).
        existing = self.checkpoint_store.get(connector_id)
        processed = (existing.documents_processed if existing else 0) + result.ingested
        mark = watermark or _utc_now()
        self.checkpoint_store.save(connector_id, scope_id, mark, processed)
        result.checkpoint_watermark = self.checkpoint_store.get(
            connector_id
        ).last_watermark  # type: ignore[union-attr]

        return result

    # ── Deletion (tombstone) ──────────────────────────────────────

    def handle_deletion(self, source_doc_id: str, scope_id: str) -> str:
        """Tombstone entities sourced from ``source_doc_id``.

        Per §3 rule 5, deletion is recorded as a tombstone —
        ``properties['tombstoned_at']`` and ``properties['valid_to']`` —
        and an ``entity_history`` row with ``change_type='deleted'``. The
        entity row is never physically removed, preserving past evidence.

        Returns ``'tombstoned'`` if any entity was marked, else
        ``'not_found'``.
        """
        # Primary lookup: the worker-maintained source index.
        rows = self.conn.execute(
            "SELECT entity_id FROM onyx_source_index WHERE source_doc_id = ?",
            (source_doc_id,),
        ).fetchall()
        entity_ids = [r["entity_id"] for r in rows]

        # Fallback: entities whose JSON properties reference the doc.
        if not entity_ids:
            entity_ids = self._find_by_property(source_doc_id, scope_id)

        if not entity_ids:
            return "not_found"

        now = _utc_now()
        for entity_id in entity_ids:
            self._tombstone_entity(entity_id, now)
        return "tombstoned"

    # ── Internals ─────────────────────────────────────────────────

    def _lookup_source(self, source_doc_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM onyx_source_index WHERE source_doc_id = ?",
            (source_doc_id,),
        ).fetchone()

    def _upsert_entity(
        self,
        envelope: Envelope,
        existing: Optional[sqlite3.Row],
    ) -> str:
        """Insert or update the entity for an envelope.

        The entity ID is derived from the stable source identity
        (``external_document_id``), so a content change on the same
        document bumps the version rather than creating a sibling.
        """
        entity_type = envelope.source_type or _DEFAULT_ENTITY_TYPE
        entity_id = entity_stable_id(
            envelope.scope_id, entity_type, envelope.external_document_id
        )

        # Version increments only when content changed (§3 rule 3).
        version = 1
        if existing is not None:
            version = int(existing["version"]) + 1

        now = _utc_now()
        properties = self._build_properties(envelope)
        self.conn.execute('''
            INSERT INTO entities
                (id, type, name, properties, created_at, updated_at,
                 version, scope_id, source_channel)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type            = excluded.type,
                name            = excluded.name,
                properties      = excluded.properties,
                updated_at      = excluded.updated_at,
                version         = excluded.version,
                scope_id        = excluded.scope_id,
                source_channel  = excluded.source_channel
        ''', (
            entity_id, entity_type, envelope.title,
            json.dumps(properties, ensure_ascii=False),
            now, now, version,
            envelope.scope_id, "onyx",
        ))

        # Record temporal version in entity_history (created/updated).
        change_type = "created" if existing is None else "updated"
        self._record_history(
            entity_id, entity_type, envelope.title,
            properties, now, change_type, version,
        )

        # Maintain the source index (idempotency + provenance).
        self.conn.execute('''
            INSERT INTO onyx_source_index
                (source_doc_id, scope_id, content_hash, entity_id,
                 version, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_doc_id) DO UPDATE SET
                scope_id     = excluded.scope_id,
                content_hash = excluded.content_hash,
                entity_id    = excluded.entity_id,
                version      = excluded.version,
                ingested_at  = excluded.ingested_at
        ''', (
            envelope.source_doc_id, envelope.scope_id,
            envelope.content_hash, entity_id, version, now,
        ))

        self.conn.commit()
        return entity_id

    def _build_properties(self, envelope: Envelope) -> dict[str, Any]:
        """Full provenance properties for the ingested entity (§3 rule 4)."""
        return {
            "title": envelope.title,
            "sections": envelope.sections,
            "source_doc_id": envelope.source_doc_id,
            "mnemosyne_source_id": envelope.mnemosyne_source_id,
            "external_document_id": envelope.external_document_id,
            "external_revision": envelope.external_revision,
            "external_uri": envelope.external_uri,
            "source_system": envelope.source_system,
            "source_type": envelope.source_type,
            "source_channel": envelope.source_channel,
            "onyx_connector_id": envelope.onyx_connector_id,
            "onyx_cc_pair_id": envelope.onyx_cc_pair_id,
            "content_hash": envelope.content_hash,
            "captured_at": envelope.captured_at,
            "source_updated_at": envelope.source_updated_at,
            "classification": envelope.classification,
            "visibility": envelope.visibility.value,
            "access_snapshot": envelope.access_snapshot.to_dict(),
            "sync_origin": envelope.sync_origin.value,
            "do_not_reimport": envelope.do_not_reimport,
        }

    def _record_history(
        self,
        entity_id: str,
        entity_type: str,
        name: str,
        properties: dict[str, Any],
        changed_at: str,
        change_type: str,
        version: int,
    ) -> None:
        self.conn.execute('''
            INSERT INTO entity_history
                (entity_id, type, name, properties, changed_at,
                 change_type, version)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            entity_id, entity_type, name,
            json.dumps(properties, ensure_ascii=False),
            changed_at, change_type, version,
        ))

    def _store_quarantine(self, record: QuarantineRecord) -> None:
        self.conn.execute('''
            INSERT INTO onyx_quarantine
                (source_doc_id, scope_id, reason, quarantined_at,
                 envelope_snapshot, resolved)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(source_doc_id) DO UPDATE SET
                scope_id           = excluded.scope_id,
                reason             = excluded.reason,
                quarantined_at     = excluded.quarantined_at,
                envelope_snapshot  = excluded.envelope_snapshot,
                resolved           = 0,
                resolved_at        = NULL,
                resolution         = NULL
        ''', (
            record.source_doc_id, record.scope_id, record.reason,
            record.quarantined_at,
            json.dumps(record.envelope_snapshot, ensure_ascii=False),
        ))
        self.conn.commit()

    def _find_by_property(
        self, source_doc_id: str, scope_id: str
    ) -> list[str]:
        """Fallback entity lookup via the JSON ``properties`` column."""
        try:
            rows = self.conn.execute(
                "SELECT id FROM entities "
                "WHERE scope_id = ? AND properties LIKE ?",
                (scope_id, f'%"{source_doc_id}"%'),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [r["id"] for r in rows]

    def _tombstone_entity(self, entity_id: str, now: str) -> None:
        row = self.conn.execute(
            "SELECT type, name, properties, version "
            "FROM entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if row is None:
            return

        properties = _parse_json(row["properties"])
        properties["tombstoned_at"] = now
        properties["valid_to"] = now
        version = int(row["version"]) if row["version"] is not None else 1
        serialized = json.dumps(properties, ensure_ascii=False)

        self.conn.execute(
            "UPDATE entities SET properties = ?, updated_at = ? "
            "WHERE id = ?",
            (serialized, now, entity_id),
        )
        # Record the deletion in history (§3 rule 5: retain past evidence).
        self.conn.execute('''
            INSERT INTO entity_history
                (entity_id, type, name, properties, changed_at,
                 change_type, version)
            VALUES (?, ?, ?, ?, ?, 'deleted', ?)
        ''', (
            entity_id, row["type"], row["name"], serialized, now, version,
        ))
        self.conn.commit()


def _parse_json(raw: Any) -> dict[str, Any]:
    """Safely parse a JSON column value."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}

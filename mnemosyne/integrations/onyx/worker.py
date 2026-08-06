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
    PUBLISHABLE_ENTITY_TYPES,
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

_DEFAULT_ENTITY_TYPE = "document"
_CLASSIFICATION_ORDER = ("private", "confidential", "internal", "public")
ALLOWED_SOURCE_TYPES: frozenset[str] = frozenset({
    "github", "slack", "gmail", "file", "confluence", "notion", "web",
    "document",
})


def _classification_rank(level: str) -> int:
    return _CLASSIFICATION_ORDER.index(level)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_entity_type(envelope: Envelope) -> str:
    """Resolve only allowlisted inbound source types."""
    source_type = (envelope.source_type or "").strip()
    if source_type not in ALLOWED_SOURCE_TYPES:
        return _DEFAULT_ENTITY_TYPE
    if source_type in PUBLISHABLE_ENTITY_TYPES:
        return _DEFAULT_ENTITY_TYPE
    return source_type


def _safe_watermark(
    committed: list[str], unresolved: list[str], previous: str
) -> str:
    """Return the greatest committed timestamp strictly before unresolved."""
    floor = min(unresolved) if unresolved else None
    candidates = [
        timestamp for timestamp in committed
        if timestamp and (floor is None or timestamp < floor)
    ]
    if previous:
        candidates.append(previous)
    return max(candidates, default=previous)


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

    def _table_exists(self, table: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    def _init_tables(self) -> None:
        """Idempotently create the worker-owned tables in the KG DB.

        - ``onyx_source_index``: idempotency / provenance index keyed by
          the stable Onyx source document ID.
        - ``onyx_quarantine``: persisted quarantine records (§4).

        The ``entities`` and ``entity_history`` tables are owned by the
        knowledge graph and assumed to already exist.
        """
        source_info = self.conn.execute(
            "PRAGMA table_info(onyx_source_index)"
        ).fetchall()
        if source_info and not any(
            row["name"] == "scope_id" and row["pk"] == 2
            for row in source_info
        ):
            self.conn.execute(
                "ALTER TABLE onyx_source_index RENAME TO onyx_source_index_old"
            )
            source_info = []
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS onyx_source_index (
                source_doc_id  TEXT NOT NULL,
                scope_id       TEXT NOT NULL,
                content_hash   TEXT NOT NULL,
                entity_id      TEXT NOT NULL,
                version        INTEGER NOT NULL DEFAULT 1,
                ingested_at    TEXT NOT NULL,
                PRIMARY KEY (source_doc_id, scope_id)
            )
        ''')
        if self._table_exists("onyx_source_index_old"):
            self.conn.execute('''
                INSERT OR IGNORE INTO onyx_source_index
                    (source_doc_id, scope_id, content_hash, entity_id,
                     version, ingested_at)
                SELECT source_doc_id, scope_id, content_hash, entity_id,
                       version, ingested_at
                FROM onyx_source_index_old
            ''')
            self.conn.execute("DROP TABLE onyx_source_index_old")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_onyx_source_scope "
            "ON onyx_source_index(scope_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_onyx_source_entity "
            "ON onyx_source_index(entity_id)"
        )
        quarantine_info = self.conn.execute(
            "PRAGMA table_info(onyx_quarantine)"
        ).fetchall()
        if quarantine_info and not (
            any(row["name"] == "source_doc_id" and row["pk"] == 1
                for row in quarantine_info)
            and any(row["name"] == "scope_id" and row["pk"] == 2
                    for row in quarantine_info)
        ):
            self.conn.execute(
                "ALTER TABLE onyx_quarantine RENAME TO onyx_quarantine_old"
            )
            quarantine_info = []
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS onyx_quarantine (
                source_doc_id     TEXT NOT NULL,
                scope_id          TEXT NOT NULL,
                reason            TEXT NOT NULL,
                quarantined_at    TEXT NOT NULL,
                envelope_snapshot TEXT,
                resolved          INTEGER NOT NULL DEFAULT 0,
                resolved_at       TEXT,
                resolved_by       TEXT,
                resolution        TEXT,
                resolution_reason TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (source_doc_id, scope_id)
            )
        ''')
        if self._table_exists("onyx_quarantine_old"):
            old_columns = {
                row["name"] for row in self.conn.execute(
                    "PRAGMA table_info(onyx_quarantine_old)"
                ).fetchall()
            }
            columns = (
                "source_doc_id", "scope_id", "reason", "quarantined_at",
                "envelope_snapshot", "resolved", "resolved_at",
                "resolved_by", "resolution", "resolution_reason",
            )
            expressions = []
            for name in columns:
                if name not in old_columns:
                    expressions.append(
                        "0" if name == "resolved" else
                        "''" if name in {
                            "scope_id", "reason", "quarantined_at",
                            "resolution_reason",
                        } else "NULL"
                    )
                elif name in {
                    "scope_id", "reason", "quarantined_at",
                }:
                    expressions.append(f"COALESCE({name}, '')")
                else:
                    expressions.append(name)
            self.conn.execute(
                f"INSERT OR IGNORE INTO onyx_quarantine ({', '.join(columns)}) "
                f"SELECT {', '.join(expressions)} FROM onyx_quarantine_old"
            )
            self.conn.execute("DROP TABLE onyx_quarantine_old")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_onyx_quarantine_scope "
            "ON onyx_quarantine(scope_id)"
        )
        self.conn.commit()

    # ── Single-envelope processing ────────────────────────────────

    def process_envelope(self, envelope: Envelope) -> ProcessResult:
        """Process one document through validation, ACL, and ingestion."""
        errors = validate_envelope(envelope)
        if errors:
            return ProcessResult(
                status=STATUS_REJECTED,
                content_hash=envelope.content_hash,
                error="reject:contract_violation: " + "; ".join(errors),
                skipped=True,
            )

        mapping = self.config.mapping_for_connector(
            envelope.onyx_connector_id
        )
        quarantined, reason = should_quarantine(envelope, mapping)
        if quarantined:
            self._store_quarantine(create_quarantine(envelope, reason))
            return ProcessResult(
                status=STATUS_QUARANTINED,
                content_hash=envelope.content_hash,
                error=reason,
                skipped=True,
            )
        if mapping is not None:
            self._apply_mapping_policy(envelope, mapping)

        existing = self._lookup_source(
            envelope.source_doc_id, envelope.scope_id
        )
        if existing is not None:
            entity_row = self.conn.execute(
                "SELECT properties FROM entities WHERE id = ?",
                (existing["entity_id"],),
            ).fetchone()
            current_props = _parse_json(
                entity_row["properties"] if entity_row else None
            )
            if current_props.get("tombstoned_at") or current_props.get("valid_to"):
                return ProcessResult(
                    status=STATUS_REJECTED,
                    error="reject:tombstoned_source: explicit reinstatement is required",
                    skipped=True,
                )
        if (
            existing is not None
            and existing["content_hash"] == envelope.content_hash
        ):
            return ProcessResult(
                status=STATUS_NOOP,
                entity_id=existing["entity_id"],
                content_hash=envelope.content_hash,
                skipped=True,
            )

        try:
            entity_id = self._upsert_entity(envelope, existing)
        except Exception as exc:  # noqa: BLE001
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

    @staticmethod
    def _apply_mapping_policy(
        envelope: Envelope, mapping: ConnectorMapping
    ) -> None:
        """Apply the mapping classification as a restrictive floor."""
        source = envelope.classification
        floor = mapping.default_classification
        if source not in _CLASSIFICATION_ORDER:
            envelope.classification = floor
            return
        if floor not in _CLASSIFICATION_ORDER:
            envelope.classification = "private"
            return
        if _classification_rank(source) > _classification_rank(floor):
            envelope.classification = floor

    # ── Batch processing ──────────────────────────────────────────

    def process_batch(
        self,
        envelopes: list[Envelope],
        connector_id: str,
    ) -> BatchResult:
        """Process a batch and advance only past unresolved timestamps."""
        result = BatchResult(connector_id=connector_id)
        committed: list[str] = []
        unresolved: list[str] = []
        unresolved_errors: list[str] = []
        scope_id = ""

        for env in envelopes:
            result.total += 1
            scope_id = scope_id or env.scope_id
            pr = self.process_envelope(env)
            if pr.status == STATUS_INGESTED:
                result.ingested += 1
                committed.append(env.source_updated_at or env.captured_at)
            elif pr.status == STATUS_NOOP:
                result.noop += 1
                committed.append(env.source_updated_at or env.captured_at)
            elif pr.status == STATUS_QUARANTINED:
                result.quarantined += 1
                unresolved.append(env.source_updated_at or env.captured_at)
                unresolved_errors.append(pr.error)
            elif pr.status == STATUS_REJECTED:
                result.rejected += 1
                unresolved.append(env.source_updated_at or env.captured_at)
                unresolved_errors.append(pr.error)
            elif pr.status == STATUS_FAILED:
                result.failed += 1
                unresolved.append(env.source_updated_at or env.captured_at)
                unresolved_errors.append(pr.error)

        if not scope_id:
            mapping = self.config.mapping_for_connector(connector_id)
            scope_id = mapping.scope_id if mapping else ""
        existing = self.checkpoint_store.get(connector_id)
        previous = existing.last_watermark if existing else ""
        watermark = _safe_watermark(committed, unresolved, previous)
        processed = (existing.documents_processed if existing else 0) + result.ingested
        if watermark and (watermark != previous or not unresolved):
            self.checkpoint_store.save(
                connector_id, scope_id, watermark, processed
            )
        if unresolved:
            self.checkpoint_store.record_error(
                connector_id,
                "; ".join(error for error in unresolved_errors if error)
                or "unresolved export item",
            )
        checkpoint = self.checkpoint_store.get(connector_id)
        result.checkpoint_watermark = (
            checkpoint.last_watermark if checkpoint else ""
        )
        return result


    # ── Deletion (tombstone) ──────────────────────────────────────

    def handle_deletion(self, source_doc_id: str, scope_id: str) -> str:
        """Write an idempotent, scope-bound tombstone."""
        rows = self.conn.execute(
            "SELECT entity_id FROM onyx_source_index "
            "WHERE source_doc_id = ? AND scope_id = ?",
            (source_doc_id, scope_id),
        ).fetchall()
        entity_ids = [r["entity_id"] for r in rows]
        if not entity_ids:
            entity_ids = self._find_by_property(source_doc_id, scope_id)
        if not entity_ids:
            return "not_found"

        changed = False
        now = _utc_now()
        for entity_id in entity_ids:
            changed = self._tombstone_entity(entity_id, now) or changed
        return "tombstoned" if changed else "tombstoned_noop"

    def resolve_quarantine(
        self,
        source_doc_id: str,
        scope_id: str,
        *,
        actor: str,
        decision: str,
        reason: str = "",
    ) -> str:
        """Apply an explicit, auditable quarantine decision."""
        if not actor:
            return "reject:replay_unauthorized"
        row = self.conn.execute(
            "SELECT * FROM onyx_quarantine "
            "WHERE source_doc_id = ? AND scope_id = ? AND resolved = 0",
            (source_doc_id, scope_id),
        ).fetchone()
        if row is None:
            return "not_found"
        if decision == "reject":
            self.conn.execute(
                "UPDATE onyx_quarantine SET resolved=1, resolved_at=?, "
                "resolved_by=?, resolution='rejected', resolution_reason=? "
                "WHERE source_doc_id=? AND scope_id=?",
                (_utc_now(), actor, reason, source_doc_id, scope_id),
            )
            self.conn.commit()
            return "rejected"
        if decision != "replay":
            return "reject:replay_unauthorized"
        snapshot = _parse_json(row["envelope_snapshot"])
        envelope = Envelope.from_dict(snapshot)
        return self.replay_quarantine(
            source_doc_id, scope_id, actor=actor, envelope=envelope,
            reason=reason,
        ).status

    def replay_quarantine(
        self,
        source_doc_id: str,
        scope_id: str,
        *,
        actor: str,
        envelope: Envelope,
        reason: str = "",
    ) -> ProcessResult:
        """Re-run validation, scope mapping, ACL, and ingestion."""
        if not actor:
            return ProcessResult(
                status=STATUS_REJECTED, error="reject:replay_unauthorized",
                skipped=True,
            )
        if envelope.source_doc_id != source_doc_id or envelope.scope_id != scope_id:
            return ProcessResult(
                status=STATUS_REJECTED, error="reject:replay_unauthorized",
                skipped=True,
            )
        result = self.process_envelope(envelope)
        if result.status != STATUS_QUARANTINED:
            self.conn.execute(
                "UPDATE onyx_quarantine SET resolved=1, resolved_at=?, "
                "resolved_by=?, resolution='replayed', resolution_reason=? "
                "WHERE source_doc_id=? AND scope_id=? AND resolved=0",
                (_utc_now(), actor, reason, source_doc_id, scope_id),
            )
            self.conn.commit()
        return result

    def reinstate(
        self,
        source_doc_id: str,
        scope_id: str,
        *,
        actor: str,
        reason: str,
    ) -> str:
        """Explicitly clear a tombstone and make withdrawn state pending."""
        if not actor or not reason:
            return "reject:replay_unauthorized"
        row = self._lookup_source(source_doc_id, scope_id)
        if row is None:
            return "not_found"
        entity = self.conn.execute(
            "SELECT type, name, properties, version FROM entities WHERE id=?",
            (row["entity_id"],),
        ).fetchone()
        if entity is None:
            return "not_found"
        properties = _parse_json(entity["properties"])
        if not (properties.get("tombstoned_at") or properties.get("valid_to")):
            return "not_found"
        properties.pop("tombstoned_at", None)
        properties.pop("valid_to", None)
        now = _utc_now()
        properties["reinstated_by"] = actor
        properties["reinstated_reason"] = reason
        serialized = json.dumps(properties, ensure_ascii=False)
        self.conn.execute(
            "UPDATE entities SET properties=?, updated_at=? WHERE id=?",
            (serialized, now, row["entity_id"]),
        )
        self._record_history(
            row["entity_id"], entity["type"], entity["name"],
            properties, now, "reinstated", int(entity["version"] or 1),
        )
        if self._table_exists("onyx_push_state"):
            self.conn.execute(
                "UPDATE onyx_push_state SET status='pending', error='' "
                "WHERE entity_id=? AND scope_id=? AND status='withdrawn'",
                (row["entity_id"], scope_id),
            )
        self.conn.commit()
        return "reinstated"

    # ── Internals ─────────────────────────────────────────────────

    def _lookup_source(
        self, source_doc_id: str, scope_id: str = ""
    ) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM onyx_source_index "
            "WHERE source_doc_id = ? AND scope_id = ?",
            (source_doc_id, scope_id),
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
        entity_type = _resolve_entity_type(envelope)
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

        self.conn.execute('''
            INSERT INTO onyx_source_index
                (source_doc_id, scope_id, content_hash, entity_id,
                 version, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_doc_id, scope_id) DO UPDATE SET
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
            "owner_id": envelope.owner_id,
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
            ON CONFLICT(source_doc_id, scope_id) DO UPDATE SET
                reason             = excluded.reason,
                quarantined_at     = excluded.quarantined_at,
                envelope_snapshot  = excluded.envelope_snapshot,
                resolved           = 0,
                resolved_at        = NULL,
                resolved_by        = NULL,
                resolution         = NULL,
                resolution_reason  = ''
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

    def _tombstone_entity(self, entity_id: str, now: str) -> bool:
        row = self.conn.execute(
            "SELECT type, name, properties, version "
            "FROM entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if row is None:
            return False

        properties = _parse_json(row["properties"])
        if properties.get("tombstoned_at") or properties.get("valid_to"):
            return False
        properties["tombstoned_at"] = now
        properties["valid_to"] = now
        version = int(row["version"]) if row["version"] is not None else 1
        serialized = json.dumps(properties, ensure_ascii=False)

        self.conn.execute(
            "UPDATE entities SET properties = ?, updated_at = ? "
            "WHERE id = ?",
            (serialized, now, entity_id),
        )
        self.conn.execute('''
            INSERT INTO entity_history
                (entity_id, type, name, properties, changed_at,
                 change_type, version)
            VALUES (?, ?, ?, ?, ?, 'deleted', ?)
        ''', (
            entity_id, row["type"], row["name"], serialized, now, version,
        ))
        self.conn.commit()
        return True


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

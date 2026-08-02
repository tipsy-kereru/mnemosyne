"""Push orchestrator: Mnemosyne curated knowledge → Onyx.

Selects publishable entities from a scope, maps them to Onyx documents,
skips no-ops (same content hash), pushes via :class:`OnyxClient`, and
records accepted/indexed/failed state.

Implements the §6 Phase 1 principles:
- Publish curated knowledge types only (not raw dumps).
- Maintain stable document IDs and doc_updated_at.
- Record API *accepted* and *indexed* as separate states.
- Exclude ``do_not_reimport`` documents.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional

from mnemosyne.integrations.onyx.client import (
    IngestResult,
    OnyxClient,
    PushStatus,
)
from mnemosyne.integrations.onyx.contract import PUBLISHABLE_ENTITY_TYPES
from mnemosyne.integrations.onyx.mapper import MapResult, map_entity
from mnemosyne.integrations.onyx.sync_state import SyncStateStore

logger = logging.getLogger(__name__)


@dataclass
class PushOutcome:
    """Aggregate result of pushing a scope."""

    scope_id: str
    total: int = 0
    pushed: int = 0        # newly accepted
    noop: int = 0          # same hash, skipped
    skipped: int = 0       # wrong type or loop guard
    failed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def add(self, document_id: str, action: str, **extra: Any) -> None:
        self.details.append(
            {"document_id": document_id, "action": action, **extra}
        )


class OnyxPushExporter:
    """Coordinates the Mnemosyne → Onyx push flow.

    Args:
        kg_conn: Open SQLite connection to the knowledge graph.
        client: Configured :class:`OnyxClient`.
        sync_store: :class:`SyncStateStore` for state persistence.
        dry_run: If True, map and report without pushing.
    """

    def __init__(
        self,
        kg_conn: sqlite3.Connection,
        client: Optional[OnyxClient],
        sync_store: SyncStateStore,
        dry_run: bool = False,
    ) -> None:
        self.conn = kg_conn
        self.client = client
        self.sync_store = sync_store
        self.dry_run = dry_run

    def push_scope(self, scope_id: str) -> PushOutcome:
        """Push all publishable entities in a scope to Onyx."""
        outcome = PushOutcome(scope_id=scope_id)
        entities = self._query_scope_entities(scope_id)

        for row in entities:
            outcome.total += 1
            entity_id = row["id"]
            entity_type = row["type"]
            entity_name = row["name"]
            properties = _parse_json(row["properties"])
            updated_at = row["updated_at"]
            source_channel = row["source_channel"] if "source_channel" in row.keys() else ""
            version = row["version"] if "version" in row.keys() else 1

            mapped = map_entity(
                entity_id=entity_id,
                entity_type=entity_type,
                entity_name=entity_name,
                properties=properties,
                scope_id=scope_id,
                updated_at=updated_at,
                source_channel=source_channel,
                version=version,
            )

            if mapped.skipped:
                outcome.skipped += 1
                outcome.add(
                    entity_id, "skipped", reason=mapped.skip_reason
                )
                continue

            # ── No-op: same content hash already accepted/indexed ──
            if self.sync_store.is_noop(mapped.document_id, mapped.content_hash):
                outcome.noop += 1
                self.sync_store.mark_noop(mapped.document_id)
                outcome.add(
                    mapped.document_id, "noop",
                    content_hash=mapped.content_hash,
                )
                continue

            if self.dry_run:
                outcome.pushed += 1
                outcome.add(
                    mapped.document_id, "dry_run",
                    title=mapped.title,
                    content_hash=mapped.content_hash,
                )
                continue

            # ── Record push attempt then push ──
            self.sync_store.record_push(
                document_id=mapped.document_id,
                scope_id=scope_id,
                entity_type=entity_type,
                entity_id=entity_id,
                content_hash=mapped.content_hash,
            )

            result = self._do_push(mapped)
            if result.status == PushStatus.ACCEPTED:
                outcome.pushed += 1
                self.sync_store.mark_accepted(mapped.document_id)
                outcome.add(
                    mapped.document_id, "accepted",
                    status_code=result.status_code,
                    attempts=result.attempts,
                )
            else:
                outcome.failed += 1
                self.sync_store.mark_failed(
                    mapped.document_id,
                    f"{result.status.value}: {result.message}",
                )
                outcome.add(
                    mapped.document_id, "failed",
                    status=result.status.value,
                    message=result.message,
                )

        return outcome

    def _query_scope_entities(
        self, scope_id: str
    ) -> list[sqlite3.Row]:
        """Fetch publishable entities for a scope, ordered by type."""
        placeholders = ",".join("?" * len(PUBLISHABLE_ENTITY_TYPES))
        params = [scope_id] + list(PUBLISHABLE_ENTITY_TYPES)
        rows = self.conn.execute(
            f"""
            SELECT id, type, name, properties, updated_at,
                   source_channel, version
            FROM entities
            WHERE scope_id = ?
              AND type IN ({placeholders})
            ORDER BY type, name
            """,
            params,
        ).fetchall()
        return rows

    def _do_push(self, mapped: MapResult) -> IngestResult:
        """Send the mapped document to Onyx."""
        if self.client is None:
            raise RuntimeError(
                "Cannot push without an OnyxClient (dry_run=True or "
                "configure a client)"
            )
        return self.client.ingest(
            document_id=mapped.document_id,
            semantic_identifier=mapped.semantic_identifier,
            title=mapped.title,
            sections=mapped.sections,
            metadata=mapped.metadata,
            doc_updated_at=mapped.doc_updated_at,
        )


def _parse_json(raw: Any) -> dict[str, Any]:
    """Safely parse a JSON column value."""
    import json
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}

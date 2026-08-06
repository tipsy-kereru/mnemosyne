"""Push curated Mnemosyne entities to an approved Onyx destination."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional

from mnemosyne.integrations.onyx.client import IngestResult, OnyxClient, PushStatus
from mnemosyne.integrations.onyx.contract import PUBLISHABLE_ENTITY_TYPES
from mnemosyne.integrations.onyx.mapper import (
    DestinationPolicy,
    MapResult,
    map_entity,
)
from mnemosyne.integrations.onyx.sync_state import (
    PUSH_ACCEPTED,
    PUSH_INDEXED,
    PUSH_NOOP,
    PUSH_FAILED,
    PUSH_WITHDRAW_BLOCKED,
    PUSH_WITHDRAW_PENDING,
    PushState,
    SyncStateStore,
)
logger = logging.getLogger(__name__)


@dataclass
class PushOutcome:
    scope_id: str
    total: int = 0
    pushed: int = 0
    noop: int = 0
    skipped: int = 0
    failed: int = 0
    withdrawn: int = 0
    withdraw_blocked: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def add(self, document_id: str, action: str, **extra: Any) -> None:
        self.details.append({"document_id": document_id, "action": action, **extra})


class OnyxPushExporter:
    def __init__(
        self,
        kg_conn: sqlite3.Connection,
        client: Optional[OnyxClient],
        sync_store: SyncStateStore,
        dry_run: bool = False,
        destination_policy: DestinationPolicy | None = None,
    ) -> None:
        self.conn = kg_conn
        self.client = client
        self.sync_store = sync_store
        self.dry_run = dry_run
        self.destination_policy = destination_policy or DestinationPolicy()

    def push_scope(self, scope_id: str) -> PushOutcome:
        outcome = PushOutcome(scope_id=scope_id)
        for row in self._query_scope_entities(scope_id):
            outcome.total += 1
            entity_id = row["id"]
            properties = _parse_json(row["properties"])
            mapped = map_entity(
                entity_id=entity_id,
                entity_type=row["type"],
                entity_name=row["name"],
                properties=properties,
                scope_id=scope_id,
                destination_policy=self.destination_policy,
                updated_at=row["updated_at"],
                source_channel=row["source_channel"] if "source_channel" in row.keys() else "",
                version=row["version"] if "version" in row.keys() else 1,
            )
            if mapped.skipped:
                outcome.skipped += 1
                outcome.add(entity_id, "skipped", reason=mapped.skip_reason)
                continue
            if self.sync_store.is_noop(mapped.document_id, mapped.content_hash):
                outcome.noop += 1
                if not self.dry_run:
                    self.sync_store.mark_noop(mapped.document_id)
                outcome.add(mapped.document_id, "noop", content_hash=mapped.content_hash)
                continue
            if self.dry_run:
                outcome.pushed += 1
                outcome.add(mapped.document_id, "dry_run", content_hash=mapped.content_hash)
                continue
            self.sync_store.record_push(
                mapped.document_id, scope_id, row["type"], entity_id,
                mapped.content_hash,
            )
            result = self._do_push(mapped)
            if result.status == PushStatus.ACCEPTED:
                outcome.pushed += 1
                self.sync_store.mark_accepted(mapped.document_id)
                outcome.add(mapped.document_id, "accepted", status_code=result.status_code)
            else:
                outcome.failed += 1
                self.sync_store.mark_failed(
                    mapped.document_id, f"{result.status.value}: {result.message}"
                )
        self._withdraw_pass(scope_id, outcome)
        return outcome

    def _withdraw_pass(self, scope_id: str, outcome: PushOutcome) -> None:
        for state in self._withdrawal_candidates(scope_id):
            reason = self._withdrawal_reason(state)
            if self.dry_run:
                outcome.withdraw_blocked += 1 if not self.destination_policy.supports_withdrawal else 0
                outcome.withdrawn += 1 if self.destination_policy.supports_withdrawal else 0
                outcome.add(state.document_id, "withdraw_dry_run", reason=reason)
                continue
            if not self.destination_policy.supports_withdrawal:
                self.sync_store.mark_withdraw_blocked(
                    state.document_id, f"withdraw:blocked_no_capability: {reason}"
                )
                outcome.withdraw_blocked += 1
                outcome.add(state.document_id, "withdraw_blocked", reason=reason)
                continue
            if self.client is None:
                raise RuntimeError("withdrawal requires an OnyxClient")
            self.sync_store._update_status(
                state.document_id, PUSH_WITHDRAW_PENDING
            )
            result = self.client.withdraw(state.document_id)
            if result.status == PushStatus.ACCEPTED:
                self.sync_store.mark_withdrawn(state.document_id)
                outcome.withdrawn += 1
                outcome.add(state.document_id, "withdrawn", reason=reason)
            else:
                self.sync_store.mark_withdraw_blocked(
                    state.document_id, f"withdraw:{reason}: {result.message}"
                )
                outcome.withdraw_blocked += 1
                outcome.add(state.document_id, "withdraw_blocked", reason=reason)

    def _withdrawal_candidates(self, scope_id: str) -> list[PushState]:
        candidates: list[PushState] = []
        for state in self.sync_store.list_scope(scope_id):
            if state.status not in {
                PUSH_ACCEPTED, PUSH_INDEXED, PUSH_NOOP, PUSH_FAILED,
                PUSH_WITHDRAW_PENDING, PUSH_WITHDRAW_BLOCKED,
            }:
                continue
            row = self.conn.execute(
                "SELECT id, type, name, properties, updated_at, source_channel, version "
                "FROM entities WHERE id=? AND scope_id=?",
                (state.entity_id, scope_id),
            ).fetchone()
            if row is None:
                candidates.append(state)
                continue
            props = _parse_json(row["properties"])
            if props.get("tombstoned_at") or props.get("valid_to"):
                candidates.append(state)
                continue
            mapped = map_entity(
                state.entity_id, row["type"], row["name"], props, scope_id,
                destination_policy=self.destination_policy,
                updated_at=row["updated_at"],
                source_channel=row["source_channel"] if "source_channel" in row.keys() else "",
                version=row["version"] if "version" in row.keys() else 1,
            )
            if mapped.skipped:
                candidates.append(state)
        return candidates

    def _withdrawal_reason(self, state: PushState) -> str:
        row = self.conn.execute(
            "SELECT properties FROM entities WHERE id=? AND scope_id=?",
            (state.entity_id, state.scope_id),
        ).fetchone()
        if row is None:
            return "withdraw:entity_missing"
        props = _parse_json(row["properties"])
        if props.get("tombstoned_at") or props.get("valid_to"):
            return "withdraw:tombstoned"
        return "withdraw:policy_denied"

    def _query_scope_entities(self, scope_id: str) -> list[sqlite3.Row]:
        """Return publishable entities and inbound fallback documents."""
        entity_types = sorted(PUBLISHABLE_ENTITY_TYPES | {"document"})
        placeholders = ",".join("?" * len(entity_types))
        params = [scope_id] + entity_types
        return self.conn.execute(
            f"""SELECT id, type, name, properties, updated_at,
                       source_channel, version
                FROM entities
                WHERE scope_id = ? AND type IN ({placeholders})
                  AND (properties IS NULL OR (
                    json_extract(properties, '$.tombstoned_at') IS NULL
                    AND json_extract(properties, '$.valid_to') IS NULL
                  ))
                ORDER BY type, name""",
            params,
        ).fetchall()

    def _do_push(self, mapped: MapResult) -> IngestResult:
        if self.client is None:
            raise RuntimeError("Cannot push without an OnyxClient")
        return self.client.ingest(
            document_id=mapped.document_id,
            semantic_identifier=mapped.semantic_identifier,
            title=mapped.title,
            sections=mapped.sections,
            metadata=mapped.metadata,
            doc_updated_at=mapped.doc_updated_at,
        )


def _parse_json(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}

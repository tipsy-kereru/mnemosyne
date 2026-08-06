"""Maps Mnemosyne entities to Onyx IngestionDocument payloads.

Phase 1 principle (§6): publish curated knowledge, not raw dumps.
Only entity types in :data:`PUBLISHABLE_ENTITY_TYPES` are eligible.
Entities marked ``do_not_reimport`` (Mnemosyne-generated) are excluded
to prevent push→export loops (§9 위험).

The mapper is stateless; all state lives in :mod:`sync_state`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from mnemosyne.integrations.onyx.acl import is_acl_fresh
from mnemosyne.integrations.onyx.contract import (
    AccessSnapshot,
    PUBLISHABLE_ENTITY_TYPES,
    compute_content_hash,
    onyx_publish_id,
    validate_outbound_document,
)

logger = logging.getLogger(__name__)


_CLASSIFICATION_ORDER = ("private", "confidential", "internal", "public")
_VISIBILITIES = {"private", "project", "org", "public"}


@dataclass(frozen=True)
class DestinationPolicy:
    """Outbound capability and classification ceiling for one destination."""

    destination_id: str = ""
    classification_ceiling: str = "public"
    supports_acl: bool = False
    supports_withdrawal: bool = False
    acl_ttl_hours: int = 24


class MapResult:
    """Outcome of mapping a single entity."""

    def __init__(
        self,
        document_id: str = "",
        semantic_identifier: str = "",
        title: str = "",
        sections: list[dict[str, Any]] | None = None,
        content_hash: str = "",
        metadata: dict[str, Any] | None = None,
        doc_updated_at: str = "",
        skipped: bool = False,
        skip_reason: str = "",
    ) -> None:
        self.document_id = document_id
        self.semantic_identifier = semantic_identifier
        self.title = title
        self.sections = sections or []
        self.content_hash = content_hash
        self.metadata = metadata or {}
        self.doc_updated_at = doc_updated_at
        self.skipped = skipped
        self.skip_reason = skip_reason

    @property
    def is_publishable(self) -> bool:
        return not self.skipped and bool(self.document_id)


def map_entity(
    entity_id: str,
    entity_type: str,
    entity_name: str,
    properties: dict[str, Any],
    scope_id: str,
    updated_at: str = "",
    source_channel: str = "",
    version: int = 1,
    destination_policy: DestinationPolicy | None = None,
) -> MapResult:
    """Map one curated entity while enforcing outbound policy."""
    policy = destination_policy or DestinationPolicy(
        classification_ceiling="public"
    )
    if entity_type not in PUBLISHABLE_ENTITY_TYPES:
        return MapResult(
            skipped=True,
            skip_reason="deny:type_not_publishable",
        )

    deny_reason = outbound_deny_reason(entity_type, properties, policy)
    if deny_reason:
        return MapResult(skipped=True, skip_reason=deny_reason)

    classification = properties.get("classification", "private")
    visibility = properties.get("visibility", "private")
    document_id = onyx_publish_id(scope_id, entity_type, entity_id)
    sections = _build_sections(entity_type, entity_name, properties)
    content_hash = compute_content_hash(sections)
    metadata: dict[str, Any] = {
        "source_system": "mnemosyne",
        "entity_type": entity_type,
        "scope_id": scope_id,
        "version": str(version),
        "classification": classification,
        "visibility": visibility,
        "sync_origin": "mnemosyne",
        "do_not_reimport": True,
    }
    if source_channel:
        metadata["source_channel"] = source_channel
    for provenance_key in (
        "external_uri", "external_revision", "source_updated_at"
    ):
        val = properties.get(provenance_key)
        if val:
            metadata[provenance_key] = val

    result = MapResult(
        document_id=document_id,
        semantic_identifier=f"[{entity_type}] {entity_name}",
        title=entity_name,
        sections=sections,
        content_hash=content_hash,
        metadata=metadata,
        doc_updated_at=updated_at or datetime.now(timezone.utc).isoformat(),
    )
    if validate_outbound_document(result):
        result.skipped = True
        result.skip_reason = "deny:contract_invalid"
    return result


def outbound_deny_reason(
    entity_type: str,
    properties: dict[str, Any],
    policy: DestinationPolicy,
) -> str:
    """Return a canonical deny code, or an empty string when allowed."""
    if entity_type not in PUBLISHABLE_ENTITY_TYPES:
        return "deny:type_not_publishable"
    origin = properties.get("sync_origin")
    if origin in {"mnemosyne", "onyx"} or properties.get("do_not_reimport"):
        return "deny:origin_not_republishable"
    if properties.get("tombstoned_at") or properties.get("valid_to"):
        return "deny:tombstoned"

    classification = properties.get("classification", "private")
    if classification not in _CLASSIFICATION_ORDER:
        return "deny:classification_unknown"
    if policy.classification_ceiling not in _CLASSIFICATION_ORDER:
        return "deny:destination_ceiling_invalid"
    if (
        _CLASSIFICATION_ORDER.index(policy.classification_ceiling)
        > _CLASSIFICATION_ORDER.index(classification)
    ):
        return "deny:classification_exceeds_destination"

    visibility = properties.get("visibility", "private")
    if visibility not in _VISIBILITIES:
        return "deny:visibility_unknown"
    if visibility != "public":
        if not policy.supports_acl:
            return "deny:destination_cannot_represent_acl"
        snapshot = AccessSnapshot.from_dict(properties.get("access_snapshot"))
        if not is_acl_fresh(snapshot, ttl_hours=policy.acl_ttl_hours):
            return "deny:acl_snapshot_missing_or_stale"
    return ""


def _outbound_policy_error(
    props: dict[str, Any], policy: DestinationPolicy
) -> str:
    """Backward-compatible private alias for the canonical gate."""
    return outbound_deny_reason("decision", props, policy)



def _build_sections(
    entity_type: str,
    name: str,
    props: dict[str, Any],
) -> list[dict[str, Any]]:
    """Render entity properties as Onyx sections (text + optional link)."""
    sections: list[dict[str, Any]] = []

    # Primary section: entity summary.
    summary_lines = [f"# {name}", f"**Type:** {entity_type}"]

    # Include key properties as structured text.
    display_props = _select_display_properties(entity_type, props)
    if display_props:
        summary_lines.append("")
        summary_lines.append("## Details")
        for key, label in display_props:
            val = props.get(key)
            if val is not None:
                summary_lines.append(f"- **{label}:** {val}")

    link = props.get("external_uri", "")
    section: dict[str, Any] = {"text": "\n".join(summary_lines)}
    if link:
        section["link"] = link
    sections.append(section)

    return sections


def _select_display_properties(
    entity_type: str, props: dict[str, Any]
) -> list[tuple[str, str]]:
    """Choose which properties to highlight per entity type."""
    templates: dict[str, list[tuple[str, str]]] = {
        "requirement": [
            ("status", "Status"),
            ("priority", "Priority"),
            ("requested_by", "Requested by"),
            ("description", "Description"),
        ],
        "decision": [
            ("outcome", "Outcome"),
            ("decided_by", "Decided by"),
            ("decided_at", "Decided at"),
            ("rationale", "Rationale"),
        ],
        "meeting": [
            ("date", "Date"),
            ("attendees", "Attendees"),
            ("summary", "Summary"),
            ("action_items", "Action items"),
        ],
        "action-item": [
            ("assignee", "Assignee"),
            ("due_date", "Due date"),
            ("status", "Status"),
        ],
        "risk": [
            ("severity", "Severity"),
            ("likelihood", "Likelihood"),
            ("mitigation", "Mitigation"),
        ],
        "conflict": [
            ("description", "Description"),
            ("resolution", "Resolution"),
            ("status", "Status"),
        ],
        "release": [
            ("version", "Version"),
            ("date", "Date"),
            ("changes", "Changes"),
        ],
        "project": [
            ("language", "Language"),
            ("repository", "Repository"),
            ("status", "Status"),
        ],
    }
    return templates.get(entity_type, [])

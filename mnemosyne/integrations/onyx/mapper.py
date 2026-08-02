"""Maps Mnemosyne entities to Onyx IngestionDocument payloads.

Phase 1 principle (§6): publish curated knowledge, not raw dumps.
Only entity types in :data:`PUBLISHABLE_ENTITY_TYPES` are eligible.
Entities marked ``do_not_reimport`` (Mnemosyne-generated) are excluded
to prevent push→export loops (§9 위험).

The mapper is stateless; all state lives in :mod:`sync_state`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from mnemosyne.integrations.onyx.contract import (
    PUBLISHABLE_ENTITY_TYPES,
    compute_content_hash,
    onyx_publish_id,
)

logger = logging.getLogger(__name__)


class MapResult:
    """Outcome of mapping a single entity.

    ``skipped`` entities are excluded from push (wrong type or loop guard).
    """

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
) -> MapResult:
    """Map a single Mnemosyne entity to an Onyx document.

    Args:
        entity_id: The entity's stable ID in the KG.
        entity_type: Must be in :data:`PUBLISHABLE_ENTITY_TYPES`.
        entity_name: Human-readable name / title.
        properties: Entity properties dict from the KG.
        scope_id: The scope this entity belongs to.
        updated_at: Last update timestamp.
        source_channel: Origin channel.
        version: Entity version number.

    Returns:
        A :class:`MapResult`. Check ``.skipped`` before pushing.
    """
    # ── Type filter: only curated knowledge types ──
    if entity_type not in PUBLISHABLE_ENTITY_TYPES:
        return MapResult(
            skipped=True,
            skip_reason=f"type {entity_type!r} not in publishable set",
        )

    # ── Loop guard: Mnemosyne-generated content must not re-enter ──
    if properties.get("sync_origin") == "mnemosyne" or properties.get(
        "do_not_reimport"
    ):
        return MapResult(
            skipped=True,
            skip_reason="do_not_reimport (loop guard)",
        )

    # ── Stable document ID ──
    document_id = onyx_publish_id(scope_id, entity_type, entity_id)

    # ── Build sections from entity properties ──
    sections = _build_sections(entity_type, entity_name, properties)

    # ── Content hash for no-op detection ──
    content_hash = compute_content_hash(sections)

    # ── Metadata: provenance + classification ──
    metadata: dict[str, Any] = {
        "source_system": "mnemosyne",
        "entity_type": entity_type,
        "scope_id": scope_id,
        "version": str(version),
    }
    if source_channel:
        metadata["source_channel"] = source_channel
    # Carry external provenance forward if available.
    for provenance_key in ("external_uri", "external_revision", "source_updated_at"):
        val = properties.get(provenance_key)
        if val:
            metadata[provenance_key] = val

    doc_updated_at = updated_at or datetime.now(timezone.utc).isoformat()

    return MapResult(
        document_id=document_id,
        semantic_identifier=f"[{entity_type}] {entity_name}",
        title=entity_name,
        sections=sections,
        content_hash=content_hash,
        metadata=metadata,
        doc_updated_at=doc_updated_at,
    )


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

    # Raw properties for full-text search (not shown in UI title).
    extra = {k: v for k, v in props.items()
             if k not in dict(display_props) and v is not None}
    if extra:
        summary_lines.append("")
        summary_lines.append("## Additional Attributes")
        for k, v in sorted(extra.items()):
            summary_lines.append(f"- **{k}:** {v}")

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

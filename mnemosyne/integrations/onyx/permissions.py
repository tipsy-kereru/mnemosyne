"""Classification-based access control and provenance citation.

Implements Phase 4 §6:
- scope_id, actor, classification filters on MCP/CLI search
- ACL-expired documents default to private (deny)
- source URL, revision, captured_at included in citations
- agent memory write gated behind explicit approval or policy

The classification hierarchy is ordered most→least restrictive:

    private > confidential > internal > public

A caller with ``internal`` clearance can see ``internal`` and ``public``
but NOT ``confidential`` or ``private``. Unknown classification
defaults to ``private`` (default deny — §4: "ACL snapshot 만료 문서는
기본 비공개").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Ordered most→least restrictive. Index 0 = most sensitive.
CLASSIFICATION_ORDER: tuple[str, ...] = (
    "private",
    "confidential",
    "internal",
    "public",
)

# Unknown / missing classification is treated as the most restrictive.
DEFAULT_CLASSIFICATION = "private"


def classification_rank(level: str) -> int:
    """Numeric rank: 0=private (most sensitive), 3=public (least).

    Unknown levels map to 0 (default deny).
    """
    try:
        return CLASSIFICATION_ORDER.index(level)
    except ValueError:
        return 0


def can_access(entity_classification: str, caller_max_level: str) -> bool:
    """True when the caller's clearance permits seeing the entity.

    ``caller_max_level`` is the most sensitive classification the caller
    is cleared for. An entity is visible only if its classification rank
    is >= the caller's rank (less sensitive or equal).
    """
    return classification_rank(entity_classification) >= classification_rank(
        caller_max_level
    )


def filter_by_classification(
    entities: list[dict[str, Any]],
    caller_max_level: str = "internal",
    classification_key: str = "classification",
) -> list[dict[str, Any]]:
    """Filter a list of entity dicts by classification clearance.

    Each entity is expected to have ``properties`` (dict) which may
    contain a ``classification`` key. Missing classification defaults
    to :data:`DEFAULT_CLASSIFICATION` (deny).
    """
    result = []
    for entity in entities:
        props = entity.get("properties") or {}
        classification = props.get(classification_key, DEFAULT_CLASSIFICATION)
        if can_access(classification, caller_max_level):
            result.append(entity)
    return result


# ── Provenance citation ─────────────────────────────────────────────

@dataclass
class Provenance:
    """Source provenance attached to search results and citations.

    Populated from entity properties when available (§4: "source URL,
    revision, captured_at을 citation에 포함").
    """

    source_uri: str = ""
    external_revision: str = ""
    captured_at: str = ""
    source_channel: str = ""
    scope_id: str = ""
    classification: str = DEFAULT_CLASSIFICATION

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v}

    @property
    def has_provenance(self) -> bool:
        return bool(self.source_uri or self.external_revision or self.captured_at)


def extract_provenance(properties: dict[str, Any]) -> Provenance:
    """Extract provenance fields from entity properties.

    Handles both flat properties (``classification``) and nested
    envelope-style properties (``external_uri``, ``external_revision``).
    """
    return Provenance(
        source_uri=properties.get("external_uri", "")
        or properties.get("source_uri", ""),
        external_revision=properties.get("external_revision", "")
        or properties.get("source_revision", ""),
        captured_at=properties.get("captured_at", ""),
        source_channel=properties.get("source_channel", ""),
        scope_id=properties.get("scope_id", ""),
        classification=properties.get(
            "classification", DEFAULT_CLASSIFICATION
        ),
    )


def enrich_results_with_provenance(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add a ``provenance`` key to each result dict.

    Non-destructive: only adds the ``provenance`` key, preserves all
    existing fields.
    """
    enriched = []
    for result in results:
        props = result.get("properties") or {}
        result["provenance"] = extract_provenance(props).to_dict()
        enriched.append(result)
    return enriched


# ── Memory write policy ─────────────────────────────────────────────

# Entity types that represent curated, high-stakes knowledge and require
# explicit review before an agent can write them (§4 UC-04, §9 위험:
# "LLM 추출 결과를 곧바로 사실로 만들지 않는다"). All other types
# (person, task, function, note, etc.) are observational and auto-writable.
REVIEW_REQUIRED_TYPES = frozenset({
    "requirement",
    "decision",
    "risk",
    "conflict",
    "blocker",
    "release",
})


def requires_review(
    entity_type: str,
    auto_write: bool = False,
) -> bool:
    """Decide whether an entity write requires review.

    Only high-stakes curated types (requirement, decision, risk, conflict,
    blocker, release) require review by default. All other types are
    observational and auto-writable. ``auto_write=True`` always bypasses.

    Args:
        entity_type: The entity type being written.
        auto_write: Explicit opt-in flag from the caller.

    Returns:
        True if the write must go through ReviewPending.
    """
    if auto_write:
        return False
    return entity_type in REVIEW_REQUIRED_TYPES

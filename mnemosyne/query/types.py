"""Core data structures for SPEC-NLQUERY-001 (T1 QueryPlan schema).

These dataclasses are the contract between router -> executor -> synthesizer.
They are deliberately plain (no Pydantic) to match the rest of mnemosyne and
keep zero new dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal

# REQ-NL-001 intent taxonomy. ``search`` is the low-confidence fallback (R-NL-002).
Intent = Literal[
    "entity_lookup",
    "relation_query",
    "path_query",
    "search",
    "longdoc_retrieve",
]


@dataclass
class QueryPlan:
    """Router output describing how to execute an NL question (REQ-NL-001).

    Attributes
    ----------
    intent:
        One of the five routing intents. ``search`` is the fallback.
    target_entities:
        GLiNER2-extracted entity names (or heuristically detected tokens).
    target_relations:
        Relation keywords detected (e.g. ``["calls", "imports"]``).
    scope:
        Scope filters passed through from the caller (scope_id/project/channel).
    confidence:
        Router self-reported confidence in [0.0, 1.0]. Below the fallback
        threshold the router rewrites intent to ``search`` (R-NL-002).
    raw_dsl:
        Precomputed DSL when the heuristic is confident enough to skip
        re-serialization; ``None`` lets the executor build the DSL itself.
    """

    intent: Intent
    target_entities: List[str] = field(default_factory=list)
    target_relations: List[str] = field(default_factory=list)
    scope: Dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    raw_dsl: str | None = None


@dataclass
class Citation:
    """A single grounded reference into a RetrievalResult entry (REQ-NL-008).

    The ``(type, id)`` pair is the canonical key the synthesizer uses to
    drop LLM-hallucinated references.
    """

    type: Literal["entity", "relation", "excerpt"]
    id: str
    source_file: str | None = None
    node_path: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"type": self.type, "id": self.id}
        if self.source_file is not None:
            out["source_file"] = self.source_file
        if self.node_path is not None:
            out["node_path"] = self.node_path
        return out

    def key(self) -> tuple[str, str]:
        """Canonical allowlist key used by the citation integrity guard."""
        return (self.type, self.id)


@dataclass
class RetrievalResult:
    """Unified retrieval payload returned by QueryExecutor (REQ-NL-002).

    ``citations`` is the canonical allowlist for REQ-NL-008: every citation
    carried into the synthesizer MUST trace to one of these entries.
    """

    entities: List[Dict[str, Any]] = field(default_factory=list)
    relations: List[Dict[str, Any]] = field(default_factory=list)
    excerpts: List[Dict[str, Any]] = field(default_factory=list)
    citations: List[Citation] = field(default_factory=list)

    def allowlist(self) -> set[tuple[str, str]]:
        """Return the set of valid citation keys (REQ-NL-008)."""
        return {c.key() for c in self.citations}

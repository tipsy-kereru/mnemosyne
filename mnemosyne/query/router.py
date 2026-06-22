"""SPEC-NLQUERY-001 REQ-NL-001: NL intent router.

``NLQueryRouter.route(question)`` maps a natural-language question to a
:class:`QueryPlan` using GLiNER2 entity extraction (when available) plus a
deterministic keyword heuristic. Low-confidence plans fall back to the
``search`` intent (R-NL-002).
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from mnemosyne.query.types import Intent, QueryPlan

logger = logging.getLogger(__name__)

FALLBACK_CONFIDENCE = 0.4

_RELATION_KEYWORDS: Dict[str, str] = {
    "calls": "calls",
    "imports": "imports",
    "uses": "uses",
    "use": "uses",
    "depends on": "depends_on",
    "depends_on": "depends_on",
    "references": "references",
    "invokes": "calls",
}

_LONGDOC_TOKENS = ("document", "section", "chapter", "page", "manual", "spec")
_LONGDOC_MIN_TOKENS = 40

_STOP = {
    "what", "who", "where", "when", "why", "how", "which", "the", "a", "an",
    "is", "are", "was", "were", "do", "does", "did", "can", "could", "should",
    "would", "will", "this", "that", "these", "those", "and", "or", "of", "to",
    "in", "on", "for", "with", "from", "by", "at",
}


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"\s+", text.lower().strip()) if t]


def _extract_entities_gliner(text: str) -> List[str]:
    """Best-effort GLiNER2 entity extraction; returns [] on any failure."""
    try:
        from mnemosyne.extraction.semantic.slm_extractor import GLiNER2Extractor

        ents = GLiNER2Extractor().extract(
            text,
            entity_types=["function", "class", "module", "person", "organization"],
        )
        seen: List[str] = []
        for e in ents:
            name = e.text.strip()
            if name and name not in seen:
                seen.append(name)
        return seen
    except Exception as exc:  # pragma: no cover - optional dep absence
        logger.debug("GLiNER2 routing extraction skipped: %s", exc)
        return []


def _heuristic_entities(text: str) -> List[str]:
    """Capitalized / backticked / identifier-like tokens as entity signal."""
    out: List[str] = []
    for m in re.finditer(r"`([A-Za-z_][\w.]*)`", text):
        out.append(m.group(1))
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9_]*)\b", text):
        out.append(m.group(1))
    for m in re.finditer(r"\b([a-z][\w]*(?:_|-)[\w]*)\b", text):
        out.append(m.group(1))
    lowered = text.lower()
    if any(kw in lowered for kw in _RELATION_KEYWORDS):
        for m in re.finditer(r"\b([a-z]{4,})\b", text):
            tok = m.group(1)
            if tok not in _STOP and tok not in _RELATION_KEYWORDS:
                out.append(tok)
    seen: List[str] = []
    for n in out:
        if n not in seen:
            seen.append(n)
    return seen


class NLQueryRouter:
    """REQ-NL-001: NL question -> QueryPlan (GLiNER2 + heuristics)."""

    def __init__(self, use_gliner: bool = True) -> None:
        self.use_gliner = use_gliner

    def route(
        self,
        question: str,
        scope: Optional[Dict[str, str]] = None,
    ) -> QueryPlan:
        """Return a QueryPlan for *question*.

        On low confidence the plan's intent is rewritten to ``search`` (R-NL-002).
        """
        scope = scope or {}
        q = question.strip()
        lowered = q.lower()

        entities: List[str] = []
        if self.use_gliner:
            entities = _extract_entities_gliner(q)
        if not entities:
            entities = _heuristic_entities(q)

        intent, relations, confidence, dsl = self._classify(lowered, q, entities)

        plan = QueryPlan(
            intent=intent,
            target_entities=entities,
            target_relations=relations,
            scope=dict(scope),
            confidence=confidence,
            raw_dsl=dsl,
        )

        if confidence < FALLBACK_CONFIDENCE and intent != "search":
            plan.intent = "search"
            plan.raw_dsl = None

        return plan

    @staticmethod
    def _classify(
        lowered: str,
        original: str,
        entities: List[str],
    ) -> tuple[Intent, List[str], float, Optional[str]]:
        """Return (intent, relations, confidence, raw_dsl)."""
        rel_hits = [
            rt for kw, rt in _RELATION_KEYWORDS.items() if kw in lowered
        ]
        if rel_hits and entities:
            rels: List[str] = []
            for r in rel_hits:
                if r not in rels:
                    rels.append(r)
            return ("relation_query", rels, 0.85, f"relation:{rels[0]}")

        if ("path" in lowered or "between" in lowered) and len(entities) >= 2:
            return (
                "path_query",
                [],
                0.75,
                f"path:{entities[0]},{entities[1]}",
            )

        if (
            any(tok in lowered for tok in _LONGDOC_TOKENS)
            and len(_tokenize(original)) >= _LONGDOC_MIN_TOKENS
        ):
            return ("longdoc_retrieve", [], 0.7, None)

        if len(entities) == 1:
            return ("entity_lookup", [], 0.65, None)
        if entities:
            return ("entity_lookup", [], 0.55, None)

        return ("search", [], 0.3, f"search:{original}")

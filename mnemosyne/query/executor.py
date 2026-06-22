"""SPEC-NLQUERY-001 REQ-NL-002: hybrid retrieval executor.

``QueryExecutor.run(plan)`` dispatches a :class:`QueryPlan` to the correct
substrate:

- ``entity_lookup``/``relation_query``/``path_query`` -> ``KnowledgeGraph.query``
- ``search`` -> ``KnowledgeGraph.query("search:...")`` (FTS5)
- ``longdoc_retrieve`` -> ``LongDocRetriever.retrieve``

Returns a unified :class:`RetrievalResult` whose ``citations`` list is the
canonical allowlist consumed by :class:`AnswerSynthesizer` (REQ-NL-008).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from mnemosyne.query.types import Citation, QueryPlan, RetrievalResult

logger = logging.getLogger(__name__)


class QueryExecutor:
    """REQ-NL-002: run a QueryPlan against the graph + longdoc substrates."""

    def __init__(self, kg: Any, longdoc_retriever: Optional[Any] = None) -> None:
        self.kg = kg
        self.longdoc_retriever = longdoc_retriever

    def run(self, plan: QueryPlan) -> RetrievalResult:
        """Execute *plan* and return a unified RetrievalResult."""
        scope_mods = self._scope_modifiers(plan)
        if plan.intent == "search":
            return self._run_search(plan, scope_mods)
        if plan.intent == "longdoc_retrieve":
            return self._run_longdoc(plan)
        # Graph intents share the DSL path.
        return self._run_graph(plan, scope_mods)

    @staticmethod
    def _scope_modifiers(plan: QueryPlan) -> str:
        """Translate ``plan.scope`` into ``@project:..@channel:..`` modifiers."""
        parts: List[str] = []
        if plan.scope.get("project"):
            parts.append(f"@project:{plan.scope['project']}")
        if plan.scope.get("source_channel"):
            parts.append(f"@channel:{plan.scope['source_channel']}")
        return "".join(parts)

    # -- graph path --------------------------------------------------------

    def _run_graph(
        self, plan: QueryPlan, scope_mods: str
    ) -> RetrievalResult:
        dsl = plan.raw_dsl or self._build_graph_dsl(plan)
        if not dsl:
            return self._run_search(plan, scope_mods)
        full = f"{dsl}{scope_mods}"
        logger.debug("QueryExecutor graph DSL: %s", full)
        raw = self.kg.query(full)
        return self._materialize_graph_result(raw)

    def _build_graph_dsl(self, plan: QueryPlan) -> str:
        """Synthesize a DSL when the router did not precompute one."""
        ents = plan.target_entities
        if plan.intent == "relation_query" and plan.target_relations:
            return f"relation:{plan.target_relations[0]}"
        if plan.intent == "path_query" and len(ents) >= 2:
            return f"path:{ents[0]},{ents[1]}"
        if plan.intent == "entity_lookup" and ents:
            return f"entity:*[{ents[0]}]"
        # Nothing confident -> caller falls through to search.
        return ""

    def _materialize_graph_result(self, raw: Dict[str, Any]) -> RetrievalResult:
        """Turn a KnowledgeGraph.query result dict into a RetrievalResult."""
        result = RetrievalResult()
        rtype = raw.get("type", "")
        rows = raw.get("results", [])
        if not isinstance(rows, list):
            rows = []
        if rtype == "entity_query":
            for row in rows:
                if not isinstance(row, dict) or "id" not in row:
                    continue
                result.entities.append(row)
                result.citations.append(
                    Citation(type="entity", id=str(row["id"]))
                )
        elif rtype == "relation_query":
            for row in rows:
                if not isinstance(row, dict) or "id" not in row:
                    continue
                result.relations.append(row)
                result.citations.append(
                    Citation(type="relation", id=str(row["id"]))
                )
        else:
            # path queries / search / unknown shapes: treat as generic rows.
            for row in rows:
                if not isinstance(row, dict):
                    continue
                rid = row.get("id")
                if rid is None:
                    continue
                result.entities.append(row)
                result.citations.append(
                    Citation(type="entity", id=str(rid))
                )
        return result

    # -- search path -------------------------------------------------------

    def _run_search(
        self, plan: QueryPlan, scope_mods: str
    ) -> RetrievalResult:
        # Use the first target entity if present, else the raw plan tokens.
        term = (
            plan.target_entities[0]
            if plan.target_entities
            else _join_scope_text(plan)
        )
        if not term:
            return RetrievalResult()
        full = f"search:{term}{scope_mods}"
        logger.debug("QueryExecutor search DSL: %s", full)
        raw = self.kg.query(full)
        return self._materialize_graph_result(raw)

    # -- longdoc path ------------------------------------------------------

    def _run_longdoc(self, plan: QueryPlan) -> RetrievalResult:
        result = RetrievalResult()
        if self.longdoc_retriever is None:
            logger.debug("longdoc_retrieve requested but no retriever wired")
            return result
        query_text = _join_scope_text(plan) or " ".join(plan.target_entities)
        # doc_hash is unknown for ad-hoc NL queries; the retriever iterates
        # active trees when given an empty doc_hash via the executor helper.
        hits = self._retrieve_across_trees(query_text)
        for hit in hits:
            excerpt = {
                "node_path": hit.get("node_path"),
                "summary": hit.get("summary"),
                "raw_excerpt": hit.get("raw_excerpt"),
                "score": hit.get("score", 0.0),
            }
            result.excerpts.append(excerpt)
            node_path = hit.get("node_path")
            nid = node_path or f"excerpt_{len(result.excerpts)}"
            result.citations.append(
                Citation(type="excerpt", id=str(nid), node_path=node_path)
            )
        return result

    def _retrieve_across_trees(self, query_text: str) -> List[Dict[str, Any]]:
        """Score every active long-doc tree for *query_text*.

        The NL layer does not know which document a user means, so we scan
        all active trees and keep the top results across them.
        """
        if self.longdoc_retriever is None:
            return []
        retriever = self.longdoc_retriever
        try:
            tree_ids = self._active_tree_ids()
        except Exception as exc:  # pragma: no cover - DB-shape variance
            logger.debug("active tree lookup failed: %s", exc)
            return []
        out: List[Dict[str, Any]] = []
        for tree_id, doc_hash in tree_ids:
            try:
                hits = retriever.retrieve(query_text, doc_hash, top_k=3)
            except Exception as exc:  # pragma: no cover - retriever robustness
                logger.debug("longdoc retrieve failed for %s: %s", doc_hash, exc)
                continue
            for h in hits:
                h.setdefault("node_path", f"{tree_id}:{h.get('node_path', '')}")
                out.append(h)
        out.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return out[:5]

    def _active_tree_ids(self) -> List[tuple[str, str]]:
        """Return ``[(tree_id, source_hash), ...]`` for active long-doc trees."""
        rows = self.kg.conn.execute(
            "SELECT tree_id, source_hash FROM document_trees "
            "WHERE status='active' ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        out: List[tuple[str, str]] = []
        for r in rows:
            tid = r["tree_id"] if hasattr(r, "keys") else r[0]
            sh = r["source_hash"] if hasattr(r, "keys") else r[1]
            out.append((str(tid), str(sh)))
        return out


def _join_scope_text(plan: QueryPlan) -> str:
    """Best-effort query text for search/longdoc intents."""
    ents = plan.target_entities
    if ents:
        return " ".join(ents)
    # Fall back to the raw_dsl search term when the router set one.
    if plan.raw_dsl and plan.raw_dsl.startswith("search:"):
        return plan.raw_dsl[len("search:") :]
    return ""

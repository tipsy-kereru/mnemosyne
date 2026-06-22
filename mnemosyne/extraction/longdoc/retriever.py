"""SPEC-LONGDOC-001 REQ-LD-004: vectorless long-doc retriever.

``LongDocRetriever.retrieve(query, doc_hash, top_k=5)`` resolves the active
tree for *doc_hash*, scores each node by:

    1. FTS5 bm25 match on the node summary (or LIKE fallback when FTS5 is
       unavailable), and
    2. a +1.0 boost when any of the node's ``entity_refs`` appears as a
       whitespace-separated token in *query*.

No embeddings; no vector similarity. Returns ``top_k`` results sorted by
score descending. Each result carries ``{node_path, summary, raw_excerpt,
score}``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Dict, List

from mnemosyne.graph.fts import fts5_compile_available

logger = logging.getLogger(__name__)

ENTITY_BOOST = 1.0


def _query_tokens(query: str) -> List[str]:
    """Lowercase, alphanumeric token list extracted from *query*."""
    out: List[str] = []
    buf: List[str] = []
    for ch in query.lower():
        if ch.isalnum():
            buf.append(ch)
        else:
            if buf:
                out.append("".join(buf))
                buf = []
    if buf:
        out.append("".join(buf))
    return out


class LongDocRetriever:
    """REQ-LD-004: FTS5 + entity-overlap retriever over ``tree_nodes``.

    Parameters
    ----------
    conn : sqlite3.Connection
        Shared KnowledgeGraph connection. ``row_factory`` should be
        ``sqlite3.Row`` (KnowledgeGraph sets this in ``__init__``).
    include_superseded : bool
        When False (default, R-LD-004 mitigation) only nodes from the active
        tree are scored. When True, all trees for *doc_hash* are considered.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        include_superseded: bool = False,
    ) -> None:
        self.conn = conn
        self.include_superseded = include_superseded
        self._fts_available = fts5_compile_available(conn)
        # FTS5 mirror presence is checked lazily per query.

    def _fts_match(
        self, tree_id: str, query: str
    ) -> Dict[str, float]:
        """Return ``{node_id: fts_score}`` for nodes matching *query* via FTS5.

        ``fts_score`` is ``1.0 / (1.0 + abs(bm25))`` so better (lower) bm25
        ranks map to higher scores in a bounded [0, 1] range.
        """
        out: Dict[str, float] = {}
        fts_ready = False
        try:
            row = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tree_node_fts'"
            ).fetchone()
            fts_ready = self._fts_available and row is not None
        except sqlite3.Error:
            fts_ready = False

        if not fts_ready:
            return out

        term = " ".join(_query_tokens(query)) or query
        if not term.strip():
            return out
        try:
            rows = self.conn.execute(
                "SELECT node_id, bm25(tree_node_fts) AS rank "
                "FROM tree_node_fts "
                "WHERE tree_node_fts MATCH ? AND tree_id=? "
                "ORDER BY rank LIMIT 100",
                (f"{term}*", tree_id),
            ).fetchall()
        except sqlite3.OperationalError:
            return out

        for r in rows:
            nid = r["node_id"] if isinstance(r, sqlite3.Row) else r[0]
            rank = r["rank"] if isinstance(r, sqlite3.Row) else r[1]
            try:
                rank_f = float(rank)
            except (TypeError, ValueError):
                rank_f = 0.0
            out[nid] = 1.0 / (1.0 + abs(rank_f))
        return out

    def _like_match(self, tree_id: str, query: str) -> Dict[str, float]:
        """LIKE fallback: 0.5 score for any node whose summary, path, or raw
        excerpt contains a query token.

        Searches across ``summary``, ``path``, and ``raw_excerpt`` so that
        degraded-mode nodes (summary NULL after SLM+LLM failure) are still
        retrievable by heading text or body excerpt.
        """
        out: Dict[str, float] = {}
        tokens = _query_tokens(query)
        if not tokens:
            return out
        like_clause = " OR ".join(
            ["summary LIKE ? OR path LIKE ? OR raw_excerpt LIKE ?" for _ in tokens]
        )
        params: List[Any] = []
        for t in tokens:
            like_pat = f"%{t}%"
            params.extend([like_pat, like_pat, like_pat])
        params.append(tree_id)
        try:
            rows = self.conn.execute(
                f"SELECT node_id FROM tree_nodes WHERE ({like_clause}) AND tree_id=?",
                params,
            ).fetchall()
        except sqlite3.Error:
            return out
        for r in rows:
            nid = r["node_id"] if isinstance(r, sqlite3.Row) else r[0]
            out[nid] = 0.5
        return out

    def retrieve(
        self,
        query: str,
        doc_hash: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Return up to *top_k* nodes ranked by FTS5 score + entity boost.

        Each result dict has keys: ``node_path``, ``summary``,
        ``raw_excerpt``, ``score``.

        When ``include_superseded`` is True, nodes from ALL trees for
        *doc_hash* are scored (R-LD-004 mitigation). Otherwise only the
        active tree is considered.
        """
        if top_k <= 0:
            return []

        tree_ids = self._resolve_tree_ids(doc_hash)
        if not tree_ids:
            return []
        # Single-tree fast path keeps the original signatures intact.
        results: List[Dict[str, Any]] = []
        for tree_id in tree_ids:
            results.extend(self._retrieve_one(query, tree_id, top_k))
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def _resolve_tree_ids(self, doc_hash: str) -> List[str]:
        """Return tree IDs for *doc_hash* (active-only or all per the flag)."""
        cur = self.conn.cursor()
        if self.include_superseded:
            rows = cur.execute(
                "SELECT tree_id FROM document_trees WHERE source_hash=? "
                "ORDER BY created_at DESC",
                (doc_hash,),
            ).fetchall()
        else:
            rows = cur.execute(
                "SELECT tree_id FROM document_trees "
                "WHERE source_hash=? AND status='active' "
                "ORDER BY created_at DESC",
                (doc_hash,),
            ).fetchall()
        out: List[str] = []
        for r in rows:
            out.append(r["tree_id"] if isinstance(r, sqlite3.Row) else r[0])
        return out

    def _retrieve_one(
        self, query: str, tree_id: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """Score nodes for a single resolved *tree_id*."""

        fts_scores = self._fts_match(tree_id, query)
        if not fts_scores:
            fts_scores = self._like_match(tree_id, query)

        # Load all nodes for this tree once (typical long-doc trees are < 200
        # nodes, well under any size concern).
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT node_id, path, summary, entity_refs, raw_excerpt "
            "FROM tree_nodes WHERE tree_id=?",
            (tree_id,),
        ).fetchall()

        query_tokens = set(_query_tokens(query))
        results: List[Dict[str, Any]] = []
        for r in rows:
            nid = r["node_id"] if isinstance(r, sqlite3.Row) else r[0]
            path = r["path"] if isinstance(r, sqlite3.Row) else r[1]
            summary = r["summary"] if isinstance(r, sqlite3.Row) else r[2]
            refs_raw = r["entity_refs"] if isinstance(r, sqlite3.Row) else r[3]
            excerpt = r["raw_excerpt"] if isinstance(r, sqlite3.Row) else r[4]

            score = fts_scores.get(nid, 0.0)

            # Entity overlap boost: +ENTITY_BOOST per overlapping ref token.
            try:
                refs = json.loads(refs_raw or "[]")
            except (ValueError, TypeError):
                refs = []
            if query_tokens and refs:
                ref_tokens = set()
                for ref in refs:
                    if not isinstance(ref, str):
                        continue
                    for tok in _query_tokens(ref):
                        ref_tokens.add(tok)
                overlap = query_tokens & ref_tokens
                if overlap:
                    score += ENTITY_BOOST * len(overlap)

            # Always include nodes that either matched or have overlap; skip
            # zero-score nodes so we don't drown the top_k in irrelevant rows.
            if score <= 0.0:
                continue

            results.append({
                "node_path": path,
                "summary": summary,
                "raw_excerpt": excerpt,
                "score": score,
                "entity_refs": refs,
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

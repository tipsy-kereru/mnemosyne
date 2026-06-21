"""Tests for SPEC-LONGDOC-001 REQ-LD-004: vectorless retriever.

Covers:
- AC-4: ``retrieve(query, doc_hash, top_k=5)`` resolves active tree_id,
  scores nodes via FTS5 summary match + +1.0 entity-overlap boost, returns
  ``{node_path, summary, raw_excerpt, score}``.
- Entity overlap boosts a node whose ``entity_refs`` intersect the query.
- ``include_superseded`` flag exposes superseded trees (R-LD-004 mitigation).
"""

import json
import sqlite3

import pytest

from mnemosyne.extraction.longdoc.retriever import LongDocRetriever
from mnemosyne.graph.knowledge_graph import KnowledgeGraph


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_longdoc_retriever.db")


@pytest.fixture
def kg(db_path):
    graph = KnowledgeGraph(db_path=db_path)
    yield graph
    graph.close()


def _seed_tree(
    kg: KnowledgeGraph,
    tree_id: str,
    source_hash: str,
    nodes: list,
    status: str = "active",
    superseded_by=None,
) -> None:
    """Seed a tree with synthetic nodes (summary + entity_refs provided)."""
    cur = kg.conn.cursor()
    cur.execute(
        "INSERT INTO document_trees "
        "(tree_id, source_hash, root_node_id, created_at, superseded_by, status) "
        "VALUES (?, ?, ?, '2026-01-01T00:00:00Z', ?, ?)",
        (tree_id, source_hash, nodes[0]["node_id"], superseded_by, status),
    )
    for n in nodes:
        cur.execute(
            "INSERT INTO tree_nodes "
            "(node_id, tree_id, parent_id, path, depth, token_start, token_end, "
            "summary, entity_refs, ordinal, raw_excerpt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                n["node_id"], tree_id, n.get("parent_id"), n["path"],
                n["depth"], n["token_start"], n["token_end"],
                n.get("summary"), json.dumps(n.get("entity_refs", [])),
                n.get("ordinal", 0), n.get("raw_excerpt", ""),
            ),
        )
        if n.get("summary"):
            try:
                cur.execute(
                    "INSERT INTO tree_node_fts (node_id, tree_id, summary) "
                    "VALUES (?, ?, ?)",
                    (n["node_id"], tree_id, n["summary"]),
                )
            except sqlite3.OperationalError:
                # FTS5 table may be absent; LIKE fallback covers this.
                pass
    kg.conn.commit()


class TestRetrieveActive:
    def test_returns_expected_node_path(self, kg):
        _seed_tree(kg, "t1", "doc-A", [
            {"node_id": "n1", "path": "root/intro", "depth": 0,
             "token_start": 0, "token_end": 100, "ordinal": 0,
             "summary": "Introduction to termination clauses",
             "entity_refs": ["termination"]},
            {"node_id": "n2", "path": "root/section-2", "depth": 0,
             "token_start": 100, "token_end": 200, "ordinal": 1,
             "summary": "Payment terms and deadlines",
             "entity_refs": ["payment"]},
        ])
        r = LongDocRetriever(conn=kg.conn)
        results = r.retrieve("termination", doc_hash="doc-A", top_k=5)
        assert len(results) >= 1
        assert results[0]["node_path"] == "root/intro"
        # Result shape (AC-4).
        for x in results:
            assert set({"node_path", "summary", "raw_excerpt", "score"}).issubset(x)

    def test_entity_overlap_boosts_node(self, kg):
        """Node whose entity_refs intersect query gets +1.0 per overlap."""
        _seed_tree(kg, "t-boost", "doc-B", [
            {"node_id": "b1", "path": "root/a", "depth": 0,
             "token_start": 0, "token_end": 10, "ordinal": 0,
             "summary": "common text here", "entity_refs": []},
            {"node_id": "b2", "path": "root/b", "depth": 0,
             "token_start": 10, "token_end": 20, "ordinal": 1,
             "summary": "common text here", "entity_refs": ["acme", "vendor"]},
        ])
        r = LongDocRetriever(conn=kg.conn)
        results = r.retrieve("common acme vendor", doc_hash="doc-B", top_k=5)
        # b2 should rank strictly higher due to entity overlap boost.
        paths = [x["node_path"] for x in results]
        assert paths.index("root/b") < paths.index("root/a")
        b2_score = next(x["score"] for x in results if x["node_path"] == "root/b")
        b1_score = next(x["score"] for x in results if x["node_path"] == "root/a")
        assert b2_score > b1_score

    def test_top_k_limits_results(self, kg):
        nodes = [
            {"node_id": f"k{i}", "path": f"root/n{i}", "depth": 0,
             "token_start": i * 10, "token_end": (i + 1) * 10, "ordinal": i,
             "summary": f"shared summary {i}", "entity_refs": []}
            for i in range(10)
        ]
        _seed_tree(kg, "t-topk", "doc-C", nodes)
        r = LongDocRetriever(conn=kg.conn)
        results = r.retrieve("shared", doc_hash="doc-C", top_k=3)
        assert len(results) <= 3

    def test_no_active_tree_returns_empty(self, kg):
        r = LongDocRetriever(conn=kg.conn)
        assert r.retrieve("anything", doc_hash="missing", top_k=5) == []

    def test_top_k_zero_returns_empty(self, kg):
        _seed_tree(kg, "t-zero", "doc-D", [
            {"node_id": "z1", "path": "root/x", "depth": 0,
             "token_start": 0, "token_end": 10, "ordinal": 0,
             "summary": "anything", "entity_refs": []},
        ])
        r = LongDocRetriever(conn=kg.conn)
        assert r.retrieve("anything", doc_hash="doc-D", top_k=0) == []


class TestIncludeSuperseded:
    def test_superseded_tree_ignored_by_default(self, kg):
        _seed_tree(
            kg, "t-old", "doc-S", [
                {"node_id": "so1", "path": "root/old", "depth": 0,
                 "token_start": 0, "token_end": 10, "ordinal": 0,
                 "summary": "old summary text", "entity_refs": []},
            ],
            status="superseded", superseded_by="t-new",
        )
        _seed_tree(kg, "t-new", "doc-S", [
            {"node_id": "sn1", "path": "root/new", "depth": 0,
             "token_start": 0, "token_end": 10, "ordinal": 0,
             "summary": "new summary text", "entity_refs": []},
        ])
        r = LongDocRetriever(conn=kg.conn)
        results = r.retrieve("summary", doc_hash="doc-S", top_k=5)
        # Only the active (new) tree should be returned.
        assert all(x["node_path"] == "root/new" for x in results)

    def test_include_superseded_flag_exposes_old_tree(self, kg):
        _seed_tree(
            kg, "t-old2", "doc-S2", [
                {"node_id": "so2", "path": "root/old", "depth": 0,
                 "token_start": 0, "token_end": 10, "ordinal": 0,
                 "summary": "old summary text", "entity_refs": []},
            ],
            status="superseded", superseded_by="t-new2",
        )
        _seed_tree(kg, "t-new2", "doc-S2", [
            {"node_id": "sn2", "path": "root/new", "depth": 0,
             "token_start": 0, "token_end": 10, "ordinal": 0,
             "summary": "new summary text", "entity_refs": []},
        ])
        r = LongDocRetriever(conn=kg.conn, include_superseded=True)
        results = r.retrieve("summary", doc_hash="doc-S2", top_k=10)
        paths = {x["node_path"] for x in results}
        assert "root/old" in paths

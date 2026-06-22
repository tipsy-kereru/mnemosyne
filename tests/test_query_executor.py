"""REQ-NL-002: QueryExecutor dispatch unit tests (mocked substrates)."""

from __future__ import annotations

from typing import Any, Dict, List

from mnemosyne.query.executor import QueryExecutor
from mnemosyne.query.types import QueryPlan


class _FakeKG:
    """Captures the DSL the executor would run against KnowledgeGraph.query."""

    def __init__(self, result: Dict[str, Any]) -> None:
        self.result = result
        self.calls: List[str] = []
        self.conn = None  # not used in dispatch tests

    def query(self, dsl: str) -> Dict[str, Any]:
        self.calls.append(dsl)
        return self.result


class _FakeRetriever:
    def __init__(self, hits: List[Dict[str, Any]]) -> None:
        self.hits = hits
        self.last_query: str = ""

    def retrieve(self, query: str, doc_hash: str, top_k: int = 5) -> List[Dict[str, Any]]:
        self.last_query = query
        return self.hits if doc_hash else []


def _entity_result() -> Dict[str, Any]:
    return {
        "type": "entity_query",
        "results": [{"id": "fn_auth", "type": "function", "name": "auth"}],
    }


def _relation_result() -> Dict[str, Any]:
    return {
        "type": "relation_query",
        "results": [
            {"id": "rel_1", "source_id": "a", "target_id": "b", "relation_type": "calls"}
        ],
    }


def test_entity_lookup_dispatches_to_kg() -> None:
    kg = _FakeKG(_entity_result())
    plan = QueryPlan(intent="entity_lookup", target_entities=["auth"], confidence=0.9)
    result = QueryExecutor(kg).run(plan)
    assert kg.calls, "executor must call kg.query"
    assert result.entities[0]["id"] == "fn_auth"
    assert ("entity", "fn_auth") in result.allowlist()


def test_relation_query_dispatches_with_precomputed_dsl() -> None:
    kg = _FakeKG(_relation_result())
    plan = QueryPlan(
        intent="relation_query",
        target_relations=["calls"],
        raw_dsl="relation:calls",
        confidence=0.9,
    )
    result = QueryExecutor(kg).run(plan)
    assert kg.calls[0].startswith("relation:calls")
    assert result.relations and ("relation", "rel_1") in result.allowlist()


def test_search_intent_uses_fts_path() -> None:
    kg = _FakeKG(_entity_result())
    plan = QueryPlan(intent="search", target_entities=["auth"], confidence=0.3)
    QueryExecutor(kg).run(plan)
    assert kg.calls[0].startswith("search:auth")


def test_search_scope_modifiers_appended() -> None:
    kg = _FakeKG({"type": "search", "results": []})
    plan = QueryPlan(
        intent="search",
        target_entities=["auth"],
        scope={"project": "p1", "source_channel": "cli"},
        confidence=0.3,
    )
    QueryExecutor(kg).run(plan)
    assert "@project:p1" in kg.calls[0]
    assert "@channel:cli" in kg.calls[0]


def test_longdoc_retrieve_dispatches_to_retriever() -> None:
    kg = _FakeKG({})
    retriever = _FakeRetriever(
        [{"node_path": "root/sec", "summary": "s", "raw_excerpt": "x", "score": 1.0}]
    )
    plan = QueryPlan(intent="longdoc_retrieve", target_entities=["auth"], confidence=0.7)
    # Wire a fake conn with active-tree lookup so executor._active_tree_ids works.
    class _FakeConn:
        def execute(self, sql: str, *a: Any) -> Any:
            class _Rows:
                def fetchall(self) -> List[Any]:
                    return []
            return _Rows()
    kg.conn = _FakeConn()
    result = QueryExecutor(kg, longdoc_retriever=retriever).run(plan)
    # No active trees -> no excerpts, but no crash.
    assert result.excerpts == []


def test_longdoc_with_active_tree_emits_excerpt_citations() -> None:
    kg = _FakeKG({})
    retriever = _FakeRetriever(
        [{"node_path": "root/sec", "summary": "s", "raw_excerpt": "x", "score": 2.0}]
    )

    class _FakeConn:
        def execute(self, sql: str, *a: Any) -> Any:
            class _Row:
                def __getitem__(self, k: str) -> str:
                    return {"tree_id": "t1", "source_hash": "h1"}[k]

                def keys(self) -> List[str]:
                    return ["tree_id", "source_hash"]

            class _Rows:
                def fetchall(self) -> List[Any]:
                    return [_Row()]
            return _Rows()

    kg.conn = _FakeConn()
    plan = QueryPlan(intent="longdoc_retrieve", target_entities=["auth"], confidence=0.7)
    result = QueryExecutor(kg, longdoc_retriever=retriever).run(plan)
    assert result.excerpts
    assert any(key[0] == "excerpt" for key in result.allowlist())

"""Tests for SPEC-LONGDOC-001 REQ-LD-003: long-doc DDL (idempotent).

Covers AC-3: ``document_trees`` and ``tree_nodes`` are added via idempotent
DDL guarded by ``sqlite_master`` existence checks; instantiation is safe to
repeat; all 527 existing tests remain green (validated by the suite gate).
"""

import sqlite3

import pytest

from mnemosyne.graph.knowledge_graph import KnowledgeGraph
from mnemosyne.graph.longdoc_schema import (
    init_longdoc_schema,
    longdoc_fts_ready,
    longdoc_tables_ready,
)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_longdoc_schema.db")


@pytest.fixture
def kg(db_path):
    graph = KnowledgeGraph(db_path=db_path)
    yield graph
    graph.close()


def _has_fts5() -> bool:
    conn = sqlite3.connect(":memory:")
    try:
        opts = [r[0] for r in conn.execute("PRAGMA compile_options")]
        return "ENABLE_FTS5" in opts
    finally:
        conn.close()


FTS5_AVAILABLE = _has_fts5()


class TestLongDocSchema:
    def test_document_trees_table_created(self, kg):
        """AC-3: document_trees table is created on init."""
        tables = [
            r["name"]
            for r in kg.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "document_trees" in tables
        assert "tree_nodes" in tables

    def test_init_twice_does_not_raise(self, db_path):
        """AC-3: re-running init_longdoc_schema is a no-op, no error."""
        kg1 = KnowledgeGraph(db_path=db_path)
        # Re-invoking the helper directly must be safe.
        init_longdoc_schema(kg1.conn)
        init_longdoc_schema(kg1.conn)
        assert longdoc_tables_ready(kg1.conn)
        kg1.close()

        # Second instantiation on the same DB must also be safe.
        kg2 = KnowledgeGraph(db_path=db_path)
        assert longdoc_tables_ready(kg2.conn)
        kg2.close()

    def test_knowledge_graph_init_creates_tables(self, kg):
        """KnowledgeGraph constructor wires the longdoc DDL hook."""
        assert longdoc_tables_ready(kg.conn)

    @pytest.mark.skipif(not FTS5_AVAILABLE, reason="FTS5 not compiled in")
    def test_tree_node_fts_created_when_fts5_available(self, kg):
        """When FTS5 is available the summary mirror table exists."""
        assert longdoc_fts_ready(kg.conn)
        tables = {
            r["name"]
            for r in kg.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "tree_node_fts" in tables

    def test_document_trees_status_default(self, kg):
        """Default status is 'active' (no-delete contract foundation)."""
        cur = kg.conn.cursor()
        cur.execute(
            "INSERT INTO document_trees (tree_id, source_hash, created_at) "
            "VALUES ('t1', 'h1', '2026-01-01T00:00:00Z')"
        )
        kg.conn.commit()
        row = cur.execute(
            "SELECT status FROM document_trees WHERE tree_id='t1'"
        ).fetchone()
        assert row["status"] == "active"


# -- ISSUE-0004 AC-1: dead-code removal regression -----------------------------


def test_columns_of_removed_from_longdoc_schema() -> None:
    """_columns_of was removed (zero callers). Assert it is gone from the
    module surface and from the source text (regression against re-add)."""
    import inspect

    import mnemosyne.graph.longdoc_schema as mod

    assert not hasattr(mod, "_columns_of"), (
        "_columns_of must be removed from longdoc_schema (dead code, ISSUE-0004)"
    )
    src = inspect.getsource(mod)
    assert "_columns_of" not in src, (
        "_columns_of must not appear anywhere in longdoc_schema source"
    )

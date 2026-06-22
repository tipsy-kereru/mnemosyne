"""SPEC-LONGDOC-001 REQ-LD-003: long-doc tree storage DDL.

Idempotent schema helper that creates the ``document_trees`` and
``tree_nodes`` tables plus the ``tree_node_fts`` FTS5 virtual table over
``tree_nodes.summary``. Mirrors the additive + ``sqlite_master``-guarded
convention from ``fts.py`` (SPEC-HEADROOM-001).

No ``ALTER``; no backfill; no ``DELETE``. Re-index is expressed via the
``status`` column on ``document_trees`` ('active' -> 'superseded'), matching
the SPEC-MCP-001 no-delete contract.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import List

from mnemosyne.graph.fts import fts5_compile_available

logger = logging.getLogger(__name__)

_TREE_TABLE = "document_trees"
_NODE_TABLE = "tree_nodes"
_FTS_TABLE = "tree_node_fts"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """True iff *name* exists as a table in ``sqlite_master``."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _index_exists(conn: sqlite3.Connection, name: str) -> bool:
    """True iff *name* exists as an index in ``sqlite_master``."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _columns_of(conn: sqlite3.Connection, table: str) -> List[str]:
    """Return column names of *table* via PRAGMA table_info (raw-tuple form)."""
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def init_longdoc_schema(conn: sqlite3.Connection) -> bool:
    """Create ``document_trees`` + ``tree_nodes`` (+ FTS5 mirror), idempotently.

    Safe to call on every schema init. Returns True iff both base tables
    exist after the call (always, since CREATE TABLE IF NOT EXISTS is used).
    """
    cursor = conn.cursor()

    if not _table_exists(conn, _TREE_TABLE):
        cursor.execute(
            f"""CREATE TABLE {_TREE_TABLE} (
                tree_id TEXT PRIMARY KEY,
                source_hash TEXT NOT NULL,
                root_node_id TEXT,
                created_at TEXT NOT NULL,
                superseded_by TEXT,
                status TEXT NOT NULL DEFAULT 'active'
            )"""
        )
        logger.info("Created %s table for SPEC-LONGDOC-001", _TREE_TABLE)

    if not _table_exists(conn, _NODE_TABLE):
        cursor.execute(
            f"""CREATE TABLE {_NODE_TABLE} (
                node_id TEXT PRIMARY KEY,
                tree_id TEXT NOT NULL,
                parent_id TEXT,
                path TEXT NOT NULL,
                depth INTEGER NOT NULL,
                token_start INTEGER NOT NULL,
                token_end INTEGER NOT NULL,
                summary TEXT,
                entity_refs TEXT,
                ordinal INTEGER NOT NULL DEFAULT 0,
                raw_excerpt TEXT,
                FOREIGN KEY (tree_id) REFERENCES {_TREE_TABLE}(tree_id)
            )"""
        )
        logger.info("Created %s table for SPEC-LONGDOC-001", _NODE_TABLE)

    # Indexes used by LongDocRetriever active-tree resolution + node lookup.
    if not _index_exists(conn, "idx_document_trees_source"):
        cursor.execute(
            "CREATE INDEX idx_document_trees_source "
            f"ON {_TREE_TABLE}(source_hash, status)"
        )
    if not _index_exists(conn, "idx_tree_nodes_tree"):
        cursor.execute(
            f"CREATE INDEX idx_tree_nodes_tree ON {_NODE_TABLE}(tree_id, parent_id)"
        )

    # Optional FTS5 mirror over node summaries. Like ``entity_fts`` this is a
    # contentless FTS5 table populated/maintained by the indexer (the indexer
    # is the only writer). Falls back to LIKE when FTS5 is unavailable.
    if fts5_compile_available(conn) and not _table_exists(conn, _FTS_TABLE):
        cursor.execute(
            f"""CREATE VIRTUAL TABLE {_FTS_TABLE} USING fts5(
                node_id UNINDEXED,
                tree_id UNINDEXED,
                summary
            )"""
        )
        logger.info("Created %s FTS5 mirror for SPEC-LONGDOC-001", _FTS_TABLE)

    conn.commit()
    return True


def longdoc_tables_ready(conn: sqlite3.Connection) -> bool:
    """True iff both ``document_trees`` and ``tree_nodes`` exist."""
    return _table_exists(conn, _TREE_TABLE) and _table_exists(conn, _NODE_TABLE)


def longdoc_fts_ready(conn: sqlite3.Connection) -> bool:
    """True iff FTS5 is available AND ``tree_node_fts`` is present."""
    return fts5_compile_available(conn) and _table_exists(conn, _FTS_TABLE)

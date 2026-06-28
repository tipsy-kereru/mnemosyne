"""
Integration tests for Rust core graph module.

Tests the PyO3 bindings for graph query operations:
- query_entities
- query_relations
- find_path
- get_stats
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

import mnemosyne_core
from mnemosyne_core import (
    EntityQuery,
    RelationQuery,
    EntityResult,
    RelationResult,
    PathResult,
)


@pytest.fixture
def test_db():
    """Create a test database with sample entities and relations."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    # Create schema
    conn.execute(
        """
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            properties TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            scope_id TEXT,
            source_channel TEXT DEFAULT 'legacy'
        )
    """
    )

    conn.execute(
        """
        CREATE TABLE relations (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            properties TEXT,
            created_at TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            scope_id TEXT,
            source_channel TEXT DEFAULT 'legacy'
        )
    """
    )

    # Insert test entities
    entities = [
        ("e1", "function", "authenticateUser", "{}", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", 1, "s1", "rust"),
        ("e2", "class", "AuthService", "{}", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", 1, "s1", "rust"),
        ("e3", "function", "validateToken", "{}", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", 1, "s1", "rust"),
        ("e4", "function", "fetchUserData", "{}", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", 1, "s2", "python"),
        ("e5", "class", "UserController", "{}", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", 1, "s2", "python"),
        ("e6", "function", "logout", "{}", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", 1, None, "legacy"),
    ]

    for e in entities:
        conn.execute(
            "INSERT INTO entities (id, type, name, properties, created_at, updated_at, version, scope_id, source_channel) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            e,
        )

    # Insert test relations
    relations = [
        ("r1", "e2", "e1", "contains", "{}", "2024-01-01T00:00:00Z", 1, "s1", "rust"),
        ("r2", "e1", "e3", "calls", "{}", "2024-01-01T00:00:00Z", 1, "s1", "rust"),
        ("r3", "e5", "e4", "contains", "{}", "2024-01-01T00:00:00Z", 1, "s2", "python"),
        ("r4", "e2", "e5", "depends_on", "{}", "2024-01-01T00:00:00Z", 1, None, "rust"),
    ]

    for r in relations:
        conn.execute(
            "INSERT INTO relations (id, source_id, target_id, relation_type, properties, created_at, version, scope_id, source_channel) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            r,
        )

    conn.commit()
    conn.close()

    yield path

    # Cleanup
    os.unlink(path)


class TestRustCoreGraph:
    """Test Rust core graph module."""

    def test_query_entities_all(self, test_db):
        """Test query_entities returns all entities when no filters applied."""
        query = EntityQuery(
            search_term=None,
            entity_type=None,
            scope_id=None,
            limit=100,
        )

        results = mnemosyne_core.query_entities(test_db, query)

        assert len(results) == 6
        assert all(isinstance(r, EntityResult) for r in results)

    def test_query_entities_by_type(self, test_db):
        """Test query_entities filters by entity type."""
        query = EntityQuery(
            search_term=None,
            entity_type="function",
            scope_id=None,
            limit=100,
        )

        results = mnemosyne_core.query_entities(test_db, query)

        assert len(results) == 4
        assert all(r.entity_type == "function" for r in results)

    def test_query_entities_by_scope(self, test_db):
        """Test query_entities filters by scope."""
        query = EntityQuery(
            search_term=None,
            entity_type=None,
            scope_id="s1",
            limit=100,
        )

        results = mnemosyne_core.query_entities(test_db, query)

        assert len(results) == 3
        assert all(r.scope_id == "s1" for r in results)

    def test_query_entities_with_search_term(self, test_db):
        """Test query_entities with search term."""
        query = EntityQuery(
            search_term="auth",
            entity_type=None,
            scope_id=None,
            limit=100,
        )

        results = mnemosyne_core.query_entities(test_db, query)

        # Should match "authenticateUser" and "AuthService"
        assert len(results) >= 2
        names = [r.name for r in results]
        assert "authenticateUser" in names or "AuthService" in names

    def test_query_entities_combined_filters(self, test_db):
        """Test query_entities with type and scope filters combined."""
        query = EntityQuery(
            search_term=None,
            entity_type="class",
            scope_id="s1",
            limit=100,
        )

        results = mnemosyne_core.query_entities(test_db, query)

        assert len(results) == 1
        assert results[0].id == "e2"
        assert results[0].name == "AuthService"

    def test_query_entities_limit(self, test_db):
        """Test query_entities respects limit parameter."""
        query = EntityQuery(
            search_term=None,
            entity_type=None,
            scope_id=None,
            limit=2,
        )

        results = mnemosyne_core.query_entities(test_db, query)

        assert len(results) == 2

    def test_query_entities_result_structure(self, test_db):
        """Test EntityResult has correct structure."""
        query = EntityQuery(
            search_term=None,
            entity_type="class",
            scope_id=None,
            limit=1,
        )

        results = mnemosyne_core.query_entities(test_db, query)

        assert len(results) == 1
        r = results[0]

        assert isinstance(r.id, str)
        assert isinstance(r.entity_type, str)
        assert isinstance(r.name, str)
        assert isinstance(r.properties, str)
        assert isinstance(r.created_at, str)
        assert isinstance(r.updated_at, str)
        assert isinstance(r.version, int)
        assert r.scope_id is None or isinstance(r.scope_id, str)
        assert isinstance(r.source_channel, str)

    def test_query_relations_all(self, test_db):
        """Test query_relations returns all relations when no filters applied."""
        query = RelationQuery(
            source=None,
            relation=None,
            target=None,
            scope_id=None,
            limit=100,
        )

        results = mnemosyne_core.query_relations(test_db, query)

        assert len(results) == 4
        assert all(isinstance(r, RelationResult) for r in results)

    def test_query_relations_by_source(self, test_db):
        """Test query_relations filters by source."""
        query = RelationQuery(
            source="e2",
            relation=None,
            target=None,
            scope_id=None,
            limit=100,
        )

        results = mnemosyne_core.query_relations(test_db, query)

        assert len(results) == 2
        assert all(r.source_id == "e2" for r in results)

    def test_query_relations_by_type(self, test_db):
        """Test query_relations filters by relation type."""
        query = RelationQuery(
            source=None,
            relation="contains",
            target=None,
            scope_id=None,
            limit=100,
        )

        results = mnemosyne_core.query_relations(test_db, query)

        assert len(results) == 2
        assert all(r.relation_type == "contains" for r in results)

    def test_query_relations_by_target(self, test_db):
        """Test query_relations filters by target."""
        query = RelationQuery(
            source=None,
            relation=None,
            target="e1",
            scope_id=None,
            limit=100,
        )

        results = mnemosyne_core.query_relations(test_db, query)

        assert len(results) == 1
        assert results[0].target_id == "e1"

    def test_query_relations_by_scope(self, test_db):
        """Test query_relations filters by scope."""
        query = RelationQuery(
            source=None,
            relation=None,
            target=None,
            scope_id="s1",
            limit=100,
        )

        results = mnemosyne_core.query_relations(test_db, query)

        assert len(results) == 2
        assert all(r.scope_id == "s1" for r in results)

    def test_query_relations_combined_filters(self, test_db):
        """Test query_relations with source and type filters combined."""
        query = RelationQuery(
            source="e2",
            relation="contains",
            target=None,
            scope_id=None,
            limit=100,
        )

        results = mnemosyne_core.query_relations(test_db, query)

        assert len(results) == 1
        assert results[0].id == "r1"

    def test_query_relations_limit(self, test_db):
        """Test query_relations respects limit parameter."""
        query = RelationQuery(
            source=None,
            relation=None,
            target=None,
            scope_id=None,
            limit=2,
        )

        results = mnemosyne_core.query_relations(test_db, query)

        assert len(results) == 2

    def test_query_relations_result_structure(self, test_db):
        """Test RelationResult has correct structure."""
        query = RelationQuery(
            source="e2",
            relation=None,
            target=None,
            scope_id=None,
            limit=1,
        )

        results = mnemosyne_core.query_relations(test_db, query)

        assert len(results) >= 1
        r = results[0]

        assert isinstance(r.id, str)
        assert isinstance(r.source_id, str)
        assert isinstance(r.target_id, str)
        assert isinstance(r.relation_type, str)
        assert isinstance(r.properties, str)
        assert isinstance(r.created_at, str)
        assert isinstance(r.version, int)
        assert r.scope_id is None or isinstance(r.scope_id, str)
        assert isinstance(r.source_channel, str)

    def test_find_path_direct(self, test_db):
        """Test find_path finds direct connections."""
        result = mnemosyne_core.find_path(test_db, "AuthService", "authenticateUser")

        assert result is not None
        assert isinstance(result, PathResult)
        assert result.length == 1
        assert len(result.path) == 2
        assert result.path[0] == "e2"
        assert result.path[1] == "e1"
        assert len(result.relations) == 1
        assert result.relations[0] == "contains"

    def test_find_path_multi_hop(self, test_db):
        """Test find_path finds multi-hop paths."""
        result = mnemosyne_core.find_path(test_db, "AuthService", "validateToken")

        assert result is not None
        assert result.length == 2
        assert result.path == ["e2", "e1", "e3"]
        assert result.relations == ["contains", "calls"]

    def test_find_path_no_path(self, test_db):
        """Test find_path returns None when no path exists."""
        # e6 (logout) has no connections
        result = mnemosyne_core.find_path(test_db, "logout", "fetchUserData")

        assert result is None

    def test_find_path_unknown_entity(self, test_db):
        """Test find_path handles unknown entities gracefully."""
        with pytest.raises(Exception):  # Should raise an error
            mnemosyne_core.find_path(test_db, "UnknownEntity", "authenticateUser")

    def test_get_stats_basic(self, test_db):
        """Test get_stats returns basic statistics."""
        stats = mnemosyne_core.get_stats(test_db)

        assert stats.entity_count == 6
        assert stats.relation_count == 4
        assert stats.scope_count == 0  # No scopes table in test DB

    def test_get_stats_type_counts(self, test_db):
        """Test get_stats returns type distribution."""
        stats = mnemosyne_core.get_stats(test_db)

        import json

        type_counts = json.loads(stats.type_counts)

        assert type_counts.get("function") == 4
        assert type_counts.get("class") == 2


class TestRustCoreGraphEmpty:
    """Test graph module with empty database."""

    @pytest.fixture
    def empty_db(self):
        """Create an empty test database."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                properties TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                scope_id TEXT,
                source_channel TEXT DEFAULT 'legacy'
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE relations (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                properties TEXT,
                created_at TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                scope_id TEXT,
                source_channel TEXT DEFAULT 'legacy'
            )
        """
        )
        conn.commit()
        conn.close()

        yield path

        os.unlink(path)

    def test_query_entities_empty(self, empty_db):
        """Test query_entities on empty database."""
        query = EntityQuery(
            search_term=None,
            entity_type=None,
            scope_id=None,
            limit=100,
        )

        results = mnemosyne_core.query_entities(empty_db, query)

        assert len(results) == 0

    def test_query_relations_empty(self, empty_db):
        """Test query_relations on empty database."""
        query = RelationQuery(
            source=None,
            relation=None,
            target=None,
            scope_id=None,
            limit=100,
        )

        results = mnemosyne_core.query_relations(empty_db, query)

        assert len(results) == 0

    def test_get_stats_empty(self, empty_db):
        """Test get_stats on empty database."""
        stats = mnemosyne_core.get_stats(empty_db)

        assert stats.entity_count == 0
        assert stats.relation_count == 0

        import json

        type_counts = json.loads(stats.type_counts)
        assert len(type_counts) == 0

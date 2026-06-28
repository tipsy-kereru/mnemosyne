"""
Integration tests for Rust core database module.

Tests the PyO3 bindings for database operations:
- execute_query
- batch_insert_entities
- batch_insert_relations
- batch_update_entities
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

import mnemosyne_core
from mnemosyne_core import (
    EntityInsert,
    RelationInsert,
    EntityUpdate,
    QueryResult,
    BatchResult,
)


@pytest.fixture
def test_db():
    """Create a test database with schema."""
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
            source_channel TEXT DEFAULT 'legacy',
            content_hash TEXT
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

    # Cleanup
    os.unlink(path)


class TestRustCoreDatabase:
    """Test Rust core database module."""

    def test_execute_query_basic(self, test_db):
        """Test execute_query returns correct results."""
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO entities (id, type, name, properties, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("e1", "function", "testFunc", "{}", "2024-01-01", "2024-01-01"),
        )
        conn.commit()
        conn.close()

        result = mnemosyne_core.execute_query(
            test_db,
            "SELECT * FROM entities",
            None,
        )

        assert isinstance(result, QueryResult)
        assert result.row_count == 1

        import json
        rows = json.loads(result.rows)
        assert len(rows) == 1
        assert rows[0]["id"] == "e1"
        assert rows[0]["name"] == "testFunc"

    def test_execute_query_with_params(self, test_db):
        """Test execute_query with parameterized query."""
        conn = sqlite3.connect(test_db)
        for i in range(3):
            conn.execute(
                "INSERT INTO entities (id, type, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (f"e{i}", "entity", f"Entity{i}", "2024-01-01", "2024-01-01"),
            )
        conn.commit()
        conn.close()

        result = mnemosyne_core.execute_query(
            test_db,
            "SELECT * FROM entities WHERE name = ?",
            ["Entity1"],
        )

        assert result.row_count == 1

        import json
        rows = json.loads(result.rows)
        assert rows[0]["id"] == "e1"

    def test_batch_insert_entities_new(self, test_db):
        """Test batch_insert_entities with new entities."""
        entities = [
            EntityInsert(
                id="e1",
                entity_type="function",
                name="testFunc1",
                properties="{}",
                created_at="2024-01-01T00:00:00Z",
                updated_at="2024-01-01T00:00:00Z",
                version=1,
                scope_id=None,
                source_channel="rust",
                content_hash=None,
            ),
            EntityInsert(
                id="e2",
                entity_type="class",
                name="TestClass",
                properties='{"methods": 5}',
                created_at="2024-01-01T00:00:00Z",
                updated_at="2024-01-01T00:00:00Z",
                version=1,
                scope_id="s1",
                source_channel="rust",
                content_hash=None,
            ),
        ]

        result = mnemosyne_core.batch_insert_entities(test_db, entities)

        assert isinstance(result, BatchResult)
        assert result.inserted == 2
        assert result.updated == 0
        assert result.failed == 0

        # Verify in database
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        assert count == 2

        row = conn.execute("SELECT * FROM entities WHERE id = 'e2'").fetchone()
        assert row["name"] == "TestClass"
        assert row["scope_id"] == "s1"
        conn.close()

    def test_batch_insert_entities_update_existing(self, test_db):
        """Test batch_insert_entities updates existing entities."""
        # First insert
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO entities (id, type, name, properties, created_at, updated_at, version) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("e1", "function", "oldName", "{}", "2024-01-01", "2024-01-01", 1),
        )
        conn.commit()
        conn.close()

        # Update via batch_insert
        entities = [
            EntityInsert(
                id="e1",
                entity_type="function",
                name="newName",
                properties='{"changed": true}',
                created_at="2024-01-01T00:00:00Z",
                updated_at="2024-01-02T00:00:00Z",
                version=2,
                scope_id=None,
                source_channel="rust",
                content_hash=None,
            ),
        ]

        result = mnemosyne_core.batch_insert_entities(test_db, entities)

        assert result.inserted == 0
        assert result.updated == 1
        assert result.failed == 0

        # Verify update
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM entities WHERE id = 'e1'").fetchone()
        assert row["name"] == "newName"
        assert row["version"] == 2
        conn.close()

    def test_batch_insert_relations(self, test_db):
        """Test batch_insert_relations."""
        # First insert entities
        conn = sqlite3.connect(test_db)
        for eid in ["e1", "e2", "e3"]:
            conn.execute(
                "INSERT INTO entities (id, type, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (eid, "entity", f"Entity{eid}", "2024-01-01", "2024-01-01"),
            )
        conn.commit()
        conn.close()

        # Insert relations
        relations = [
            RelationInsert(
                id="r1",
                source_id="e1",
                target_id="e2",
                relation_type="connected_to",
                properties="{}",
                created_at="2024-01-01T00:00:00Z",
                version=1,
                scope_id=None,
                source_channel="rust",
            ),
            RelationInsert(
                id="r2",
                source_id="e2",
                target_id="e3",
                relation_type="depends_on",
                properties="{}",
                created_at="2024-01-01T00:00:00Z",
                version=1,
                scope_id="s1",
                source_channel="python",
            ),
        ]

        result = mnemosyne_core.batch_insert_relations(test_db, relations)

        assert result.inserted == 2
        assert result.updated == 0
        assert result.failed == 0

        # Verify
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        count = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        assert count == 2

        row = conn.execute("SELECT * FROM relations WHERE id = 'r2'").fetchone()
        assert row["source_id"] == "e2"
        assert row["scope_id"] == "s1"
        conn.close()

    def test_batch_update_entities_basic(self, test_db):
        """Test batch_update_entities updates entities."""
        # Insert initial entity
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO entities (id, type, name, properties, created_at, updated_at, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("e1", "function", "oldName", "{}", "2024-01-01", "2024-01-01", "hash1"),
        )
        conn.commit()
        conn.close()

        # Update
        updates = [
            EntityUpdate(
                id="e1",
                entity_type="function",
                name="newName",
                properties='{"updated": true}',
                updated_at="2024-01-02T00:00:00Z",
                scope_id=None,
                source_channel="rust",
                content_hash="hash2",
            ),
        ]

        result = mnemosyne_core.batch_update_entities(test_db, updates, skip_unchanged=False)

        assert result.updated == 1
        assert result.failed == 0

        # Verify
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM entities WHERE id = 'e1'").fetchone()
        assert row["name"] == "newName"
        assert row["content_hash"] == "hash2"
        conn.close()

    def test_batch_update_entities_skip_unchanged(self, test_db):
        """Test batch_update_entities with skip_unchanged optimization."""
        # Insert entity with content_hash
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO entities (id, type, name, properties, created_at, updated_at, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("e1", "function", "testFunc", "{}", "2024-01-01", "2024-01-01", "hash1"),
        )
        conn.commit()
        conn.close()

        # Try to update with same hash (should skip)
        updates = [
            EntityUpdate(
                id="e1",
                entity_type="function",
                name="testFunc",
                properties="{}",
                updated_at="2024-01-02T00:00:00Z",
                scope_id=None,
                source_channel="rust",
                content_hash="hash1",  # Same hash
            ),
        ]

        result = mnemosyne_core.batch_update_entities(test_db, updates, skip_unchanged=True)

        assert result.updated == 0  # Should be skipped
        assert result.failed == 0

        # Verify unchanged
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT updated_at FROM entities WHERE id = 'e1'").fetchone()
        assert row["updated_at"] == "2024-01-01"  # Should not be updated
        conn.close()

    def test_batch_update_entities_with_different_hash(self, test_db):
        """Test batch_update_entities updates when hash differs."""
        # Insert entity with content_hash
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO entities (id, type, name, properties, created_at, updated_at, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("e1", "function", "testFunc", "{}", "2024-01-01", "2024-01-01", "hash1"),
        )
        conn.commit()
        conn.close()

        # Update with different hash (should update)
        updates = [
            EntityUpdate(
                id="e1",
                entity_type="function",
                name="testFunc",
                properties="{}",
                updated_at="2024-01-02T00:00:00Z",
                scope_id=None,
                source_channel="rust",
                content_hash="hash2",  # Different hash
            ),
        ]

        result = mnemosyne_core.batch_update_entities(test_db, updates, skip_unchanged=True)

        assert result.updated == 1
        assert result.failed == 0

        # Verify updated
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT updated_at, content_hash FROM entities WHERE id = 'e1'").fetchone()
        assert row["updated_at"] == "2024-01-02T00:00:00Z"
        assert row["content_hash"] == "hash2"
        conn.close()

    def test_batch_insert_mixed_insert_update(self, test_db):
        """Test batch_insert_entities with mixed insert and update."""
        # Insert one existing entity
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO entities (id, type, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("e1", "entity", "Entity1", "2024-01-01", "2024-01-01"),
        )
        conn.commit()
        conn.close()

        # Batch with one existing (update) and one new (insert)
        entities = [
            EntityInsert(
                id="e1",
                entity_type="entity",
                name="Entity1",
                properties="{}",
                created_at="2024-01-01T00:00:00Z",
                updated_at="2024-01-02T00:00:00Z",
                version=2,
                scope_id=None,
                source_channel="rust",
                content_hash=None,
            ),
            EntityInsert(
                id="e2",
                entity_type="entity",
                name="Entity2",
                properties="{}",
                created_at="2024-01-01T00:00:00Z",
                updated_at="2024-01-01T00:00:00Z",
                version=1,
                scope_id=None,
                source_channel="rust",
                content_hash=None,
            ),
        ]

        result = mnemosyne_core.batch_insert_entities(test_db, entities)

        assert result.inserted == 1
        assert result.updated == 1
        assert result.failed == 0

    def test_execute_query_empty_result(self, test_db):
        """Test execute_query returns empty result for no matches."""
        result = mnemosyne_core.execute_query(
            test_db,
            "SELECT * FROM entities",
            None,
        )

        assert result.row_count == 0

        import json
        rows = json.loads(result.rows)
        assert len(rows) == 0

    def test_execute_query_aggregate(self, test_db):
        """Test execute_query with aggregate functions."""
        conn = sqlite3.connect(test_db)
        for i in range(5):
            conn.execute(
                "INSERT INTO entities (id, type, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (f"e{i}", "entity", f"Entity{i}", "2024-01-01", "2024-01-01"),
            )
        conn.commit()
        conn.close()

        result = mnemosyne_core.execute_query(
            test_db,
            "SELECT COUNT(*) as count, type FROM entities GROUP BY type",
            None,
        )

        assert result.row_count == 1

        import json
        rows = json.loads(result.rows)
        assert rows[0]["count"] == 5
        assert rows[0]["type"] == "entity"


class TestRustCoreDatabaseEmpty:
    """Test database module with empty database."""

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
                source_channel TEXT DEFAULT 'legacy',
                content_hash TEXT
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

    def test_batch_insert_empty(self, empty_db):
        """Test batch operations on empty database."""
        result = mnemosyne_core.batch_insert_entities(empty_db, [])
        assert result.inserted == 0
        assert result.updated == 0
        assert result.failed == 0

    def test_batch_relations_empty(self, empty_db):
        """Test batch relations on empty database."""
        result = mnemosyne_core.batch_insert_relations(empty_db, [])
        assert result.inserted == 0
        assert result.updated == 0
        assert result.failed == 0

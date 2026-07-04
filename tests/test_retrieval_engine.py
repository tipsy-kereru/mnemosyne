"""
Tests for hybrid search retrieval engine.
"""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from mnemosyne.retrieval.engine import RetrievalEngine, SearchMode, SearchResult


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    # Initialize schema
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Create basic entities table
    conn.execute("""
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
    """)

    # Create relations table
    conn.execute("""
        CREATE TABLE relations (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            properties TEXT,
            created_at TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            scope_id TEXT,
            source_channel TEXT DEFAULT 'legacy',
            FOREIGN KEY (source_id) REFERENCES entities(id),
            FOREIGN KEY (target_id) REFERENCES entities(id)
        )
    """)

    # Add test entities
    test_entities = [
        ("e1", "person", "Elon Musk", '{"aliases": ["EM"]}', "2024-01-01T00:00:00Z"),
        ("e2", "company", "Tesla", '{"aliases": ["TSLA"]}', "2024-01-01T00:00:00Z"),
        ("e3", "person", "Sam Altman", '{}', "2024-01-01T00:00:00Z"),
        ("e4", "company", "OpenAI", '{}', "2024-01-01T00:00:00Z"),
        ("e5", "event", "AI Safety Summit", '{}', "2024-01-01T00:00:00Z"),
    ]

    for eid, etype, name, props, created in test_entities:
        conn.execute(
            """
            INSERT INTO entities (id, type, name, properties, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (eid, etype, name, props, created, created),
        )

    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    db_path.unlink(missing_ok=True)


class TestSearchMode:
    """Tests for SearchMode configurations."""

    def test_conervative_mode(self):
        """Conservative mode should disable vector and graph."""
        mode = SearchMode.conservative()

        assert mode.name == "conservative"
        assert mode.use_vector is False
        assert mode.use_bm25 is True
        assert mode.use_graph is False
        assert mode.use_reranker is False

    def test_balanced_mode(self):
        """Balanced mode should enable core strategies."""
        mode = SearchMode.balanced()

        assert mode.name == "balanced"
        assert mode.use_vector is True
        assert mode.use_bm25 is True
        assert mode.use_graph is True
        assert mode.use_reranker is False

    def test_tokenmax_mode(self):
        """Tokenmax mode should enable all features."""
        mode = SearchMode.tokenmax()

        assert mode.name == "tokenmax"
        assert mode.use_vector is True
        assert mode.use_bm25 is True
        assert mode.use_graph is True
        assert mode.use_reranker is True
        assert mode.use_expansion is True


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_creation(self):
        """SearchResult should initialize correctly."""
        result = SearchResult(
            entity_id="test",
            score=0.9,
            evidence=["vector_match"],
            create_safety="exists",
        )

        assert result.entity_id == "test"
        assert result.score == 0.9
        assert "vector_match" in result.evidence
        assert result.create_safety == "exists"


class TestRetrievalEngine:
    """Tests for RetrievalEngine."""

    def test_initialization(self, temp_db):
        """Engine should initialize with database."""
        engine = RetrievalEngine(db_path=str(temp_db))

        assert engine.db_path == temp_db
        assert engine.mode.name == "balanced"

    def test_query_empty_string(self, temp_db):
        """Empty query should return empty results."""
        engine = RetrievalEngine(db_path=str(temp_db))

        results = engine.query("")
        assert results == []

        results = engine.query("   ")
        assert results == []

    def test_cache_key_generation(self, temp_db):
        """Cache keys should be deterministic."""
        engine = RetrievalEngine(db_path=str(temp_db))

        key1 = engine._make_cache_key("test query", {"type": "person"})
        key2 = engine._make_cache_key("test query", {"type": "person"})

        assert key1 == key2

        # Different queries should produce different keys
        key3 = engine._make_cache_key("different query", {"type": "person"})
        assert key2 != key3

    def test_cache_operations(self, temp_db):
        """Cache should store and retrieve results."""
        engine = RetrievalEngine(db_path=str(temp_db))

        # Create test results
        test_results = [
            SearchResult(
                entity_id="e1",
                score=0.9,
                evidence=["bm25_match"],
                create_safety="exists",
            )
        ]

        # Set cache
        cache_key = "test_key"
        engine._set_cache(cache_key, test_results)

        # Get cache
        cached_data = engine._get_cache(cache_key)
        assert cached_data is not None

        # Deserialize
        restored = engine._deserialize_results(cached_data)
        assert len(restored) == 1
        assert restored[0].entity_id == "e1"
        assert restored[0].score == 0.9

    def test_clear_cache(self, temp_db):
        """Clear cache should remove entries."""
        engine = RetrievalEngine(db_path=str(temp_db))

        # Add some cache entries
        test_results = [SearchResult(entity_id="e1", score=0.9)]
        engine._set_cache("key1", test_results)
        engine._set_cache("key2", test_results)

        # Clear all
        cleared = engine.clear_cache()
        assert cleared >= 2

        # Verify cache is empty
        assert engine._get_cache("key1") is None

    def test_serialize_deserialize_results(self, temp_db):
        """Results should serialize/deserialize correctly."""
        engine = RetrievalEngine(db_path=str(temp_db))

        original = [
            SearchResult(
                entity_id="e1",
                score=0.9,
                evidence=["vector_match", "bm25_match"],
                create_safety="exists",
                source_strategy="rrf_fusion",
            )
        ]

        serialized = engine._serialize_results(original)
        restored = engine._deserialize_results(serialized)

        assert len(restored) == len(original)
        assert restored[0].entity_id == original[0].entity_id
        assert restored[0].score == original[0].score
        assert set(restored[0].evidence) == set(original[0].evidence)


class TestSchemaMigration:
    """Tests for schema migration."""

    def test_ensure_schema(self, temp_db):
        """Schema should migrate successfully."""
        from mnemosyne.retrieval.schema import ensure_schema

        result = ensure_schema(temp_db)

        assert result is True

        # Verify tables exist
        conn = sqlite3.connect(str(temp_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        tables = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}

        assert "embeddings" in table_names
        assert "search_cache" in table_names

        conn.close()

    def test_schema_version(self, temp_db):
        """Schema version should reflect features."""
        from mnemosyne.retrieval.schema import HybridSearchSchema

        schema = HybridSearchSchema(temp_db)

        # Before migration
        version = schema.get_version()
        assert version == 0

        # After migration
        schema.migrate()
        version = schema.get_version()
        assert version >= 2  # At least embeddings + cache

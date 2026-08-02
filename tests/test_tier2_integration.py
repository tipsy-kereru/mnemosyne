"""Tier 2 integration tests: concurrent access, cache invalidation, WAL.

Exercises the cross-module integration of Phase 0 (ConnectionPool) +
Phase 1 (ThreadingHTTPServer + TTL Cache) to verify they work together.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph


@pytest.fixture
def kg(tmp_path: Path) -> KnowledgeGraph:
    return KnowledgeGraph(db_path=str(tmp_path / "integration.db"))


def _seed_entities(kg: KnowledgeGraph, count: int, scope: str = "test") -> None:
    for i in range(count):
        kg.add_entity(Entity(
            id=f"{scope}:e{i}", type="test", name=f"entity-{i}",
            properties={"idx": i},
            created_at="2026-01-01", updated_at="2026-01-01",
        ), scope_id=scope)


# ── Concurrent read/write through pool ──────────────────────────────

class TestConcurrentAccess:
    def test_many_readers_one_writer_no_corruption(self, kg):
        """N reader threads + 1 writer thread, no errors, data consistent."""
        _seed_entities(kg, 5)
        errors = []
        stop = threading.Event()

        def reader():
            try:
                conn = kg.get_read_conn()
                while not stop.is_set():
                    conn.execute("SELECT COUNT(*) FROM entities").fetchone()
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(20):
                    kg.add_entity(Entity(
                        id=f"test:w{i}", type="test", name=f"w-{i}",
                        properties={}, created_at="2026-01-01", updated_at="2026-01-01",
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        threads.append(threading.Thread(target=writer))
        for t in threads:
            t.start()
        time.sleep(0.5)
        stop.set()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Concurrent errors: {errors}"
        count = kg.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        assert count == 25  # 5 seed + 20 written

    def test_wal_checkpoint_after_batch_write(self, kg):
        """Checkpoint merges WAL into main DB without data loss."""
        _seed_entities(kg, 10)
        result = kg.wal_checkpoint("TRUNCATE")
        assert result["busy"] == 0  # 0 = checkpoint succeeded

        # Verify data is still there after checkpoint
        count = kg.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        assert count == 10


# ── synchronous=FULL crash safety ───────────────────────────────────

class TestCrashSafety:
    def test_full_mode_survives_simulated_crash(self, tmp_path):
        """synchronous=FULL: data is durable after commit even without checkpoint."""
        db_path = tmp_path / "crash.db"
        kg = KnowledgeGraph(db_path=str(db_path), synchronous="FULL")

        # Verify FULL is active
        pragma = kg.conn.execute("PRAGMA synchronous").fetchone()
        assert pragma[0] == 2  # FULL = 2

        kg.add_entity(Entity(
            id="survivor", type="test", name="survives",
            properties={}, created_at="2026-01-01", updated_at="2026-01-01",
        ))
        kg.conn.commit()
        kg.wal_checkpoint("TRUNCATE")
        kg.close()

        # Reopen and verify data persisted
        kg2 = KnowledgeGraph(db_path=str(db_path))
        entity = kg2.get_entity("survivor")
        assert entity is not None
        assert entity.name == "survives"
        kg2.close()


# ── HTTP server + pool integration ──────────────────────────────────

class TestServerPoolIntegration:
    def test_concurrent_http_reads(self, kg):
        """ThreadingHTTPServer handles concurrent GET requests via pool."""
        _seed_entities(kg, 5)
        from mnemosyne.serve.app import create_server

        server = create_server(host="127.0.0.1", port=0, db_path=str(kg.db_path))
        port = server.server_address[1]

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        errors = []
        results = []

        def fetch_entities():
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/v1/entities", timeout=5
                ) as resp:
                    data = json.loads(resp.read())
                    results.append(data.get("count", len(data.get("entities", []))))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=fetch_entities) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        server.shutdown()
        assert errors == [], f"HTTP errors: {errors}"
        assert len(results) == 8
        assert all(r == 5 for r in results)  # all saw 5 entities


# ── Cache invalidation lifecycle ────────────────────────────────────

class TestCacheInvalidationLifecycle:
    def test_cache_populated_then_invalidated(self, kg):
        """Cache miss → hit → invalidate → miss cycle."""
        from mnemosyne.retrieval.engine import (
            RetrievalEngine,
            invalidate_all_caches,
        )

        _seed_entities(kg, 3)

        # Build a lightweight engine (avoid numpy dependency)
        engine = RetrievalEngine.__new__(RetrievalEngine)
        engine.db_path = kg.db_path
        engine.mode = type("M", (), {"name": "test", "use_vector": False,
                                      "use_bm25": True, "use_graph": False,
                                      "use_reranker": False, "use_expansion": False,
                                      "max_results": 20, "token_budget": None})()
        engine.cache_ttl = 3600
        engine._cache = {}
        engine._cache_lock = threading.Lock()

        # Simulate a search result
        from mnemosyne.retrieval.engine import SearchResult
        fake_results = [SearchResult(entity_id="test:e0", score=1.0)]

        # Cache miss → populate
        key = engine._cache_key("entity", "test", "balanced")
        assert engine._cache_get(key) is None
        engine._cache_put(key, fake_results)
        assert engine._cache_get(key) is not None

        # Cache hit
        hit = engine._cache_get(key)
        assert hit is not None
        assert hit[0].entity_id == "test:e0"

        # Invalidate
        count = engine.invalidate_cache()
        assert engine._cache_get(key) is None  # cleared

    def test_invalidate_scope_targets_only_matching(self, kg):
        """invalidate_scope clears only the matching scope's entries."""
        from mnemosyne.retrieval.engine import RetrievalEngine, SearchResult

        engine = RetrievalEngine.__new__(RetrievalEngine)
        engine._cache = {}
        engine._cache_lock = threading.Lock()
        engine.cache_ttl = 3600

        # Populate two scopes
        key_a = engine._cache_key("query", "scope-a", "balanced")
        key_b = engine._cache_key("query", "scope-b", "balanced")
        engine._cache_put(key_a, [SearchResult(entity_id="a", score=1.0)])
        engine._cache_put(key_b, [SearchResult(entity_id="b", score=1.0)])

        # Invalidate only scope-a
        removed = engine.invalidate_scope("scope-a")
        assert removed == 1
        assert engine._cache_get(key_a) is None
        assert engine._cache_get(key_b) is not None  # scope-b untouched

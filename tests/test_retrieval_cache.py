"""
Tests for the in-memory TTL result cache on RetrievalEngine.

The cache (RetrievalEngine._cache / _cache_get / _cache_put /
invalidate_cache / invalidate_scope) is the fast path that sits in front of
the existing persistent SQLite cache so repeated identical queries skip the
database entirely, and is busted on KnowledgeGraph writes.

The RetrievalEngine constructor pulls in the search strategies (which require
numpy / sentence-transformers / FTS). To keep these tests hermetic and free of
those optional deps, engines are built lightweight via ``__new__`` with only
the cache attributes wired. The integration tests then drive the *real*
``query()`` control flow, stubbing only the strategy/fusion/detail seam (which
also sidesteps a pre-existing 3-tuple/2-tuple unpack mismatch in
_build_search_results that is outside this work package's scope).
"""

import threading

import pytest

from mnemosyne.retrieval.engine import (
    RetrievalEngine,
    SearchMode,
    SearchResult,
    _LIVE_ENGINES,
    invalidate_all_caches,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeClock:
    """Stand-in for the ``time`` module: only ``time()`` is used by the cache."""

    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def time(self) -> float:
        return self.now


class _StubIntent:
    """Minimal intent classifier returning a non-graph intent."""

    def classify(self, query: str) -> str:  # noqa: D401
        return "general"


def _make_engine(cache_ttl: int = 3600, mode: SearchMode | None = None):
    """Build a RetrievalEngine with only the in-memory cache wired up.

    Avoids the heavy constructor (strategies need numpy/FTS). The cache
    subsystem and query() flow do not depend on any of the omitted state.
    """
    engine = RetrievalEngine.__new__(RetrievalEngine)
    engine.mode = mode if mode is not None else SearchMode.balanced()
    engine.cache_ttl = cache_ttl
    engine._cache = {}
    engine._cache_lock = threading.Lock()
    return engine


def _make_queryable_engine(monkeypatch):
    """A lightweight engine whose search pipeline is stubbed for query() tests.

    Returns ``(engine, counter, canned_ids)`` where ``counter['runs']`` counts
    how many times the actual search executed — the signal that distinguishes a
    cache miss (runs++) from a hit (unchanged).
    """
    import sys
    import types

    # query() imports its fusion helper via the strategies package, whose
    # __init__ pulls in numpy (absent in this env). Inject numpy-free shims so
    # the real query() control flow runs; fusion is out of scope here (already
    # covered by test_fusion_strategy.py). monkeypatch restores sys.modules.
    monkeypatch.setitem(
        sys.modules,
        "mnemosyne.retrieval.strategies",
        types.ModuleType("mnemosyne.retrieval.strategies"),
    )
    _fusion_shim = types.ModuleType("mnemosyne.retrieval.strategies.fusion")
    _fusion_shim.fused_scores_with_evidence = lambda strategy_results, k=60, limit=100: []
    monkeypatch.setitem(sys.modules, "mnemosyne.retrieval.strategies.fusion", _fusion_shim)
    engine = _make_engine()
    engine.intent_classifier = _StubIntent()
    counter = {"runs": 0}
    canned = [
        SearchResult(
            entity_id="alpha",
            score=0.9,
            evidence=["bm25_match"],
            create_safety="exists",
        )
    ]

    def fake_run_strategies(queries, filters):  # noqa: ANN001
        counter["runs"] += 1
        return {"bm25": [("alpha", 1.0)]}

    monkeypatch.setattr(engine, "_run_strategies", fake_run_strategies)
    # Bypass the latent 3-tuple/2-tuple unpack in the real _build_search_results.
    monkeypatch.setattr(engine, "_build_search_results", lambda fused, sr: list(canned))
    monkeypatch.setattr(engine, "_fetch_entity_details", lambda results: results)
    # No DB connection in the lightweight engine; neuter the secondary SQLite cache.
    monkeypatch.setattr(engine, "_get_cache", lambda key: None)
    monkeypatch.setattr(engine, "_set_cache", lambda key, results: None)
    return engine, counter, ["alpha"]


# ---------------------------------------------------------------------------
# Cache key construction
# ---------------------------------------------------------------------------


class TestCacheKey:
    def test_deterministic(self):
        e = _make_engine()
        a = e._cache_key("hello", "scope1", "balanced")
        b = e._cache_key("hello", "scope1", "balanced")
        assert a == b

    def test_different_query(self):
        e = _make_engine()
        assert e._cache_key("hello", None, "balanced") != e._cache_key(
            "world", None, "balanced"
        )

    def test_different_scope(self):
        """Different scope_id must yield a different key (→ cache miss)."""
        e = _make_engine()
        assert e._cache_key("hello", "scopeA", "balanced") != e._cache_key(
            "hello", "scopeB", "balanced"
        )

    def test_different_mode(self):
        """Different search mode must yield a different key (→ cache miss)."""
        e = _make_engine()
        assert e._cache_key("hello", None, "balanced") != e._cache_key(
            "hello", None, "conservative"
        )


# ---------------------------------------------------------------------------
# get / put
# ---------------------------------------------------------------------------


class TestCacheGetPut:
    def test_miss_then_hit(self):
        e = _make_engine()
        key = e._cache_key("hello", None, "balanced")
        results = [SearchResult(entity_id="e1", score=1.0)]

        # Miss on an empty cache.
        assert e._cache_get(key) is None

        e._cache_put(key, results)
        # Hit after a put.
        got = e._cache_get(key)
        assert got is not None
        assert [r.entity_id for r in got] == ["e1"]
        assert got[0].score == 1.0

    def test_get_returns_a_copy(self):
        """Callers must not be able to mutate the cached list in place."""
        e = _make_engine()
        key = e._cache_key("hello", None, "balanced")
        e._cache_put(key, [SearchResult(entity_id="e1", score=1.0)])

        got = e._cache_get(key)
        assert got is not None
        got.clear()

        # Underlying entry is untouched.
        again = e._cache_get(key)
        assert again is not None
        assert len(again) == 1


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


class TestTTL:
    def test_entry_within_ttl_is_fresh(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr("mnemosyne.retrieval.engine.time", clock)
        e = _make_engine(cache_ttl=10)
        key = e._cache_key("q", None, "balanced")
        e._cache_put(key, [SearchResult(entity_id="e1", score=1.0)])

        clock.now += 9  # still inside the 10s window
        assert e._cache_get(key) is not None

    def test_stale_entry_is_evicted(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr("mnemosyne.retrieval.engine.time", clock)
        e = _make_engine(cache_ttl=10)
        key = e._cache_key("q", None, "balanced")
        e._cache_put(key, [SearchResult(entity_id="e1", score=1.0)])

        clock.now += 11  # past TTL
        assert e._cache_get(key) is None          # treated as a miss
        assert key not in e._cache                # lazily evicted


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


class TestInvalidation:
    def test_invalidate_cache_clears_all(self):
        e = _make_engine()
        ka = e._cache_key("a", "s1", "balanced")
        kb = e._cache_key("b", "s2", "balanced")
        e._cache_put(ka, [SearchResult(entity_id="e1", score=1.0)])
        e._cache_put(kb, [SearchResult(entity_id="e2", score=1.0)])
        assert e._cache_get(ka) is not None
        assert e._cache_get(kb) is not None

        e.invalidate_cache()

        assert e._cache_get(ka) is None
        assert e._cache_get(kb) is None
        assert e._cache == {}

    def test_invalidate_scope_clears_only_matching(self):
        e = _make_engine()
        keep_key = e._cache_key("q", "scopeB", "balanced")
        drop_key = e._cache_key("q", "scopeA", "balanced")
        e._cache_put(keep_key, [SearchResult(entity_id="keep", score=1.0)])
        e._cache_put(drop_key, [SearchResult(entity_id="drop", score=1.0)])

        removed = e.invalidate_scope("scopeA")

        assert removed == 1
        assert e._cache_get(drop_key) is None
        # The other scope is untouched.
        kept = e._cache_get(keep_key)
        assert kept is not None
        assert [r.entity_id for r in kept] == ["keep"]

    def test_invalidate_scope_no_false_prefix_match(self):
        """Invalidating 'scopeA' must not touch 'scopeA2' (delimiter safety)."""
        e = _make_engine()
        k_a = e._cache_key("q", "scopeA", "balanced")
        k_a2 = e._cache_key("q", "scopeA2", "balanced")
        e._cache_put(k_a, [SearchResult(entity_id="a", score=1.0)])
        e._cache_put(k_a2, [SearchResult(entity_id="a2", score=1.0)])

        removed = e.invalidate_scope("scopeA")

        assert removed == 1
        assert e._cache_get(k_a) is None
        assert e._cache_get(k_a2) is not None

    def test_invalidate_all_caches_hits_registered_engines(self):
        e = _make_engine()
        key = e._cache_key("q", None, "balanced")
        e._cache_put(key, [SearchResult(entity_id="e1", score=1.0)])
        assert e._cache_get(key) is not None

        # __init__ normally registers; the lightweight build does not, so
        # register explicitly to validate the registry → invalidation path.
        _LIVE_ENGINES.add(e)
        try:
            invalidated = invalidate_all_caches()
        finally:
            _LIVE_ENGINES.discard(e)

        assert invalidated >= 1
        assert e._cache_get(key) is None


# ---------------------------------------------------------------------------
# query() integration (real control flow + real cache, stubbed pipeline)
# ---------------------------------------------------------------------------


class TestQueryCacheIntegration:
    def test_first_query_miss_second_query_hit(self, monkeypatch):
        e, counter, ids = _make_queryable_engine(monkeypatch)

        r1 = e.query("hello")
        assert counter["runs"] == 1                  # miss → search executed
        assert [r.entity_id for r in r1] == ids

        r2 = e.query("hello")
        assert counter["runs"] == 1                  # hit → no second search
        assert [r.entity_id for r in r2] == ids

    def test_hit_does_not_reenter_search(self, monkeypatch):
        e, counter, _ = _make_queryable_engine(monkeypatch)
        e.query("hello")
        runs_after_first = counter["runs"]

        e.query("hello")
        e.query("hello")
        assert counter["runs"] == runs_after_first   # 2nd & 3rd served from cache

    def test_different_scope_is_a_miss(self, monkeypatch):
        e, counter, _ = _make_queryable_engine(monkeypatch)
        e.query("hello", scope_id="A")
        assert counter["runs"] == 1
        e.query("hello", scope_id="B")               # different scope → miss
        assert counter["runs"] == 2

    def test_use_cache_false_bypasses_cache(self, monkeypatch):
        e, counter, _ = _make_queryable_engine(monkeypatch)
        e.query("hello", use_cache=False)
        e.query("hello", use_cache=False)
        assert counter["runs"] == 2                  # never cached → re-searched
        assert e._cache == {}

    def test_invalidate_cache_forces_research(self, monkeypatch):
        e, counter, _ = _make_queryable_engine(monkeypatch)
        e.query("hello")
        assert counter["runs"] == 1
        e.invalidate_cache()
        e.query("hello")
        assert counter["runs"] == 2                  # cache cleared → re-search

    def test_empty_query_short_circuits(self, monkeypatch):
        e, counter, _ = _make_queryable_engine(monkeypatch)
        assert e.query("") == []
        assert e.query("   ") == []
        assert counter["runs"] == 0


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_read_write_invalidate_no_corruption(self):
        e = _make_engine()
        key = e._cache_key("q", None, "balanced")
        payload = [SearchResult(entity_id="x", score=1.0)]
        errors: list[Exception] = []

        def writer():
            try:
                for _ in range(500):
                    e._cache_put(key, payload)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def reader():
            try:
                for _ in range(500):
                    got = e._cache_get(key)
                    if got is not None:
                        assert isinstance(got, list)
                        for item in got:
                            assert isinstance(item, SearchResult)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def invalidator():
            try:
                for _ in range(200):
                    e.invalidate_cache()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = (
            [threading.Thread(target=writer) for _ in range(4)]
            + [threading.Thread(target=reader) for _ in range(4)]
            + [threading.Thread(target=invalidator) for _ in range(2)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # Cache is still in a consistent, usable state after the storm.
        e._cache_put(key, payload)
        got = e._cache_get(key)
        assert got is not None
        assert len(got) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

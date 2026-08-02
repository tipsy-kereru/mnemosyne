"""
Main orchestration engine for hybrid search.

Coordinates multiple search strategies (vector, BM25, graph) and
merges results using Reciprocal Rank Fusion (RRF).
"""

import hashlib
import json
import logging
import threading
import time
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sqlite3

logger = logging.getLogger(__name__)

# Registry of live RetrievalEngine instances. Used by invalidate_all_caches()
# to bust every engine's in-memory cache after a KnowledgeGraph write. A
# WeakSet is intentional: abandoned engines are garbage-collected without an
# explicit unregister, so the registry can never leak engines.
_LIVE_ENGINES: "weakref.WeakSet[RetrievalEngine]" = weakref.WeakSet()


@dataclass
class SearchMode:
    """Search mode bundles cost/quality knobs.

    Modes determine which strategies are enabled and resource limits.
    """
    name: str  # conservative, balanced, tokenmax
    use_vector: bool = True
    use_bm25: bool = True
    use_graph: bool = True
    use_reranker: bool = False
    use_expansion: bool = False
    max_results: int = 30
    token_budget: Optional[int] = None

    # Preset configurations
    @classmethod
    def conservative(cls) -> "SearchMode":
        """Fast search: BM25 only, no reranking."""
        return cls(
            name="conservative",
            use_vector=False,
            use_bm25=True,
            use_graph=False,
            use_reranker=False,
            max_results=20,
        )

    @classmethod
    def balanced(cls) -> "SearchMode":
        """Balanced search: Vector + BM25 with RRF fusion."""
        return cls(
            name="balanced",
            use_vector=True,
            use_bm25=True,
            use_graph=True,
            use_reranker=False,
            max_results=30,
        )

    @classmethod
    def tokenmax(cls) -> "SearchMode":
        """Maximum quality: All strategies + reranker."""
        return cls(
            name="tokenmax",
            use_vector=True,
            use_bm25=True,
            use_graph=True,
            use_reranker=True,
            use_expansion=True,
            max_results=30,
        )


@dataclass
class SearchResult:
    """Unified result with evidence tags."""
    entity_id: str
    score: float
    evidence: List[str] = field(default_factory=list)
    create_safety: str = "unknown"  # 'exists', 'probable', 'unknown'
    source_strategy: str = "fused"

    # Optional: Raw entity data
    entity_type: Optional[str] = None
    entity_name: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _CacheEntry:
    """A single entry in the in-memory result cache."""

    results: List[SearchResult]
    timestamp: float


class RetrievalEngine:
    """Main orchestration engine for hybrid search."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        mode: SearchMode = SearchMode.balanced(),
        cache_ttl_seconds: int = 3600,
    ):
        """Initialize the retrieval engine.

        Args:
            db_path: Path to SQLite database. Uses default if None.
            mode: Search mode configuration.
            cache_ttl_seconds: Cache time-to-live in seconds.
        """
        if db_path is None:
            db_path = Path.home() / "mnemosyne" / "graph" / "knowledge.db"

        self.db_path = Path(db_path)
        self.mode = mode
        self.cache_ttl = cache_ttl_seconds

        # In-memory TTL result cache (fast path; consulted before the
        # persistent SQLite cache so repeated identical queries skip the DB).
        self._cache: Dict[str, "_CacheEntry"] = {}
        self._cache_lock = threading.Lock()

        # Initialize strategies
        self._init_strategies()
        self._init_db()
        self._init_intent_classifier()

        # Register for cross-engine cache invalidation (WeakSet → auto-GC).
        _LIVE_ENGINES.add(self)

    def _init_strategies(self):
        """Initialize search strategies based on mode."""
        from mnemosyne.retrieval.strategies.bm25 import BM25Strategy
        from mnemosyne.retrieval.strategies.vector import VectorStrategy
        from mnemosyne.retrieval.strategies.graph import GraphStrategy

        self.strategies: Dict[str, Any] = {}

        if self.mode.use_bm25:
            self.strategies["bm25"] = BM25Strategy(self.db_path)

        if self.mode.use_vector:
            self.strategies["vector"] = VectorStrategy(self.db_path)

        if self.mode.use_graph:
            self.strategies["graph"] = GraphStrategy(self.db_path)

        logger.debug(f"Initialized strategies: {list(self.strategies.keys())}")

    def _init_db(self):
        """Initialize database connection and schema."""
        self.conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
        )
        self.conn.row_factory = sqlite3.Row

        # Initialize schema extensions
        self._init_schema()

    def _init_schema(self):
        """Initialize hybrid search schema extensions."""
        cursor = self.conn.cursor()

        # Embeddings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                entity_id TEXT PRIMARY KEY,
                vector BLOB,
                model TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                embedded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
            )
        """)

        # Search cache table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                cache_key TEXT PRIMARY KEY,
                results TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hits INTEGER DEFAULT 0,
                expires_at TIMESTAMP
            )
        """)

        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_embeddings_model
            ON embeddings(model, embedded_at)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_cache_expires
            ON search_cache(expires_at)
        """)

        self.conn.commit()
        logger.debug("Schema extensions initialized")

    def _init_intent_classifier(self):
        """Initialize intent classifier."""
        from mnemosyne.retrieval.intent import IntentClassifier
        self.intent_classifier = IntentClassifier()

    def query(
        self,
        query_str: str,
        filters: Optional[Dict] = None,
        explain: bool = False,
        use_cache: bool = True,
        scope_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Execute hybrid search query.

        Pipeline:
        1. Check cache
        2. Intent classification
        3. Query expansion (if enabled)
        4. Run all strategies in parallel
        5. RRF fusion
        6. Graph augmentation (if applicable)
        7. Rerank (if enabled)
        8. Apply evidence tags
        9. Cache results

        Args:
            query_str: Search query
            filters: Optional entity type filters
            explain: If True, return scoring attribution
            use_cache: Whether to use result cache

        Returns:
            List of SearchResult with evidence tags
        """
        if not query_str or not query_str.strip():
            return []

        # In-memory TTL cache — fast path; on a hit we skip all DB access.
        mem_key = self._cache_key(query_str, scope_id, self.mode.name)
        if use_cache:
            mem_cached = self._cache_get(mem_key)
            if mem_cached is not None:
                logger.debug(f"In-memory cache hit for query: {query_str[:50]}...")
                return mem_cached

        # Persistent SQLite cache (secondary, survives process restarts).
        cache_key = None
        if use_cache:
            cache_key = self._make_cache_key(query_str, filters)
            cached = self._get_cache(cache_key)
            if cached:
                logger.debug(f"Cache hit for query: {query_str[:50]}...")
                return self._deserialize_results(cached)

        # 1. Intent classification
        intent = self.intent_classifier.classify(query_str)
        logger.debug(f"Query intent: {intent}")

        # 2. Query expansion (if enabled)
        queries = self._maybe_expand(query_str, intent)

        # 3. Run all strategies in parallel
        strategy_results = self._run_strategies(queries, filters)

        # 4. RRF fusion
        from mnemosyne.retrieval.strategies.fusion import fused_scores_with_evidence

        fused = fused_scores_with_evidence(strategy_results, k=60)

        # 5. Graph augmentation (if applicable)
        if self.mode.use_graph and intent in ("entity", "relation"):
            fused = self._graph_augment(fused, query_str, intent)

        # 6. Rerank (if enabled)
        if self.mode.use_reranker:
            fused = self._rerank(fused, query_str)

        # 7. Build SearchResults with evidence
        results = self._build_search_results(fused, strategy_results)

        # 8. Fetch entity details
        results = self._fetch_entity_details(results)

        # 9. Cache results. Slice to the mode's result cap first so that an
        # in-memory hit returns exactly what a miss would.
        final_results = results[: self.mode.max_results]
        if use_cache:
            self._cache_put(mem_key, final_results)
            if cache_key:
                self._set_cache(cache_key, results)

        logger.debug(f"Query returned {len(final_results)} results")
        return final_results

    def _make_cache_key(self, query: str, filters: Optional[Dict]) -> str:
        """Generate cache key for query."""
        key_data = {"query": query, "filters": sorted((filters or {}).items())}
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()[:32]

    # ------------------------------------------------------------------
    # In-memory TTL result cache
    # ------------------------------------------------------------------

    def _cache_key(self, query: str, scope_id: Optional[str], mode_name: str) -> str:
        """Build a deterministic in-memory cache key.

        The key embeds the scope and search mode so identical queries under
        different scopes/modes never collide. Scope is kept as a plain prefix
        segment (not hashed) so invalidate_scope() can match it cheaply.
        """
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:32]
        return f"{scope_id}|{mode_name}|{query_hash}"

    def _cache_get(self, key: str) -> Optional[List["SearchResult"]]:
        """Return cached results if present and within TTL, else None.

        Stale entries are evicted lazily on read.
        """
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.time() - entry.timestamp > self.cache_ttl:
                del self._cache[key]
                return None
            # Shallow copy so callers cannot mutate the cached list.
            return list(entry.results)

    def _cache_put(self, key: str, results: List["SearchResult"]) -> None:
        """Store ``results`` under ``key`` with the current timestamp."""
        with self._cache_lock:
            self._cache[key] = _CacheEntry(
                results=list(results), timestamp=time.time()
            )

    def invalidate_cache(self) -> None:
        """Clear the entire in-memory result cache.

        Call after any KnowledgeGraph write so stale results are never served.
        """
        with self._cache_lock:
            self._cache.clear()

    def invalidate_scope(self, scope_id: Optional[str]) -> int:
        """Drop every in-memory cache entry belonging to ``scope_id``.

        Returns the number of entries removed. Cheaper than
        invalidate_cache() when only one scope changed.
        """
        prefix = f"{scope_id}|"
        with self._cache_lock:
            stale = [k for k in self._cache if k.startswith(prefix)]
            for k in stale:
                del self._cache[k]
        return len(stale)

    def _get_cache(self, cache_key: str) -> Optional[str]:
        """Get cached results if available and not expired."""
        cursor = self.conn.cursor()
        row = cursor.execute(
            """
            SELECT results, expires_at FROM search_cache
            WHERE cache_key = ? AND (expires_at IS NULL OR expires_at > ?)
            """,
            (cache_key, datetime.now().isoformat()),
        ).fetchone()

        if row:
            # Update hit counter
            cursor.execute(
                "UPDATE search_cache SET hits = hits + 1 WHERE cache_key = ?",
                (cache_key,),
            )
            self.conn.commit()
            return row[0]
        return None

    def _set_cache(self, cache_key: str, results: List[SearchResult]) -> None:
        """Cache query results."""
        expires_at = datetime.now() + timedelta(seconds=self.cache_ttl)
        results_json = self._serialize_results(results)

        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO search_cache
            (cache_key, results, expires_at)
            VALUES (?, ?, ?)
            """,
            (cache_key, results_json, expires_at.isoformat()),
        )
        self.conn.commit()

    def _serialize_results(self, results: List[SearchResult]) -> str:
        """Serialize results to JSON."""
        data = [
            {
                "entity_id": r.entity_id,
                "score": r.score,
                "evidence": r.evidence,
                "create_safety": r.create_safety,
                "source_strategy": r.source_strategy,
            }
            for r in results
        ]
        return json.dumps(data)

    def _deserialize_results(self, data: str) -> List[SearchResult]:
        """Deserialize results from JSON."""
        items = json.loads(data)
        return [
            SearchResult(
                entity_id=item["entity_id"],
                score=item["score"],
                evidence=item.get("evidence", []),
                create_safety=item.get("create_safety", "unknown"),
                source_strategy=item.get("source_strategy", "cached"),
            )
            for item in items
        ]

    def _maybe_expand(self, query: str, intent: str) -> List[str]:
        """Expand query if enabled."""
        if not self.mode.use_expansion:
            return [query]

        # Simple expansion: add lowercase variant
        variants = [query]
        if query != query.lower():
            variants.append(query.lower())

        return variants

    def _run_strategies(
        self, queries: List[str], filters: Optional[Dict]
    ) -> Dict[str, List[Tuple[str, float]]]:
        """Run all enabled strategies."""
        results = {}

        for strategy_name, strategy in self.strategies.items():
            try:
                strategy_results = []
                for query in queries:
                    strategy_results.extend(
                        strategy.search(query, limit=self.mode.max_results, filters=filters)
                    )
                results[strategy_name] = strategy_results
            except Exception as e:
                logger.warning(f"Strategy {strategy_name} failed: {e}")
                results[strategy_name] = []

        return results

    def _graph_augment(
        self, fused: List[Tuple[str, float]], query: str, intent: str
    ) -> List[Tuple[str, float]]:
        """Augment with graph traversal results."""
        # Placeholder: graph augmentation would add related entities
        return fused

    def _rerank(self, fused: List[Tuple[str, float]], query: str) -> List[Tuple[str, float]]:
        """Rerank using cross-encoder."""
        # Placeholder: cross-encoder reranking
        return fused

    def _build_search_results(
        self,
        fused: List[Tuple[str, float]],
        strategy_results: Dict[str, List[Tuple[str, float]]],
    ) -> List[SearchResult]:
        """Build SearchResult objects with evidence."""
        results = []
        entity_ids_in_result = set()

        for entity_id, score in fused:
            if entity_id in entity_ids_in_result:
                continue
            entity_ids_in_result.add(entity_id)

            # Collect evidence
            evidence = []
            for strategy_name, results in strategy_results.items():
                if any(eid == entity_id for eid, _ in results):
                    evidence.append(f"{strategy_name}_match")

            results.append(
                SearchResult(
                    entity_id=entity_id,
                    score=score,
                    evidence=evidence,
                    source_strategy="rrf_fusion",
                )
            )

        return results

    def _fetch_entity_details(self, results: List[SearchResult]) -> List[SearchResult]:
        """Fetch entity details from database."""
        if not results:
            return results

        entity_ids = [r.entity_id for r in results]
        placeholders = ",".join("?" * len(entity_ids))

        cursor = self.conn.cursor()
        rows = cursor.execute(
            f"""
            SELECT id, type, name, properties
            FROM entities
            WHERE id IN ({placeholders})
            """,
            entity_ids,
        ).fetchall()

        entity_data = {row["id"]: row for row in rows}

        for result in results:
            if result.entity_id in entity_data:
                row = entity_data[result.entity_id]
                result.entity_type = row["type"]
                result.entity_name = row["name"]
                result.properties = json.loads(row["properties"]) if row["properties"] else {}

                # Determine create_safety
                if result.entity_type:
                    result.create_safety = "exists"

        return results

    def clear_cache(self, older_than_seconds: Optional[int] = None) -> int:
        """Clear search cache.

        Args:
            older_than_seconds: Only clear entries older than this.
                If None, clears all cache entries.

        Returns:
            Number of cache entries cleared.
        """
        cursor = self.conn.cursor()

        if older_than_seconds is None:
            cursor.execute("DELETE FROM search_cache")
        else:
            cutoff = datetime.now() - timedelta(seconds=older_than_seconds)
            cursor.execute(
                "DELETE FROM search_cache WHERE created_at < ?", (cutoff.isoformat(),)
            )

        deleted = cursor.rowcount
        self.conn.commit()
        logger.info(f"Cleared {deleted} cache entries")
        return deleted



# Phase 2: KnowledgeGraph.add_entity / update_entity / tombstone_entity should
# call mnemosyne.retrieval.engine.invalidate_all_caches() after committing a
# write so stale retrieval results are evicted from every live engine.
def invalidate_all_caches() -> int:
    """Invalidate the in-memory caches of all live RetrievalEngine instances.

    Returns the number of engines whose caches were invalidated.
    """
    invalidated = 0
    for engine in list(_LIVE_ENGINES):
        engine.invalidate_cache()
        invalidated += 1
    return invalidated
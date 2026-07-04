"""
BM25 keyword search strategy.

Extends Mnemosyne's existing FTS5 search with:
- Title boost prioritization
- Alias hop for named entities
- Source-aware ranking
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mnemosyne.graph.fts import build_match_term, fts_search_ready

logger = logging.getLogger(__name__)


class BM25Strategy:
    """Enhanced BM25 search strategy using FTS5."""

    def __init__(self, db_path: Path):
        """Initialize BM25 strategy.

        Args:
            db_path: Path to SQLite database.
        """
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(
            str(self.db_path), timeout=30.0, check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row

        # Check if FTS is available
        self.fts_ready = fts_search_ready(self.conn)

        if not self.fts_ready:
            logger.warning("FTS5 not available, BM25 strategy will be limited")

    def search(
        self,
        query: str,
        limit: int = 30,
        filters: Optional[Dict] = None,
    ) -> List[Tuple[str, float]]:
        """Search by BM25 keyword matching.

        Args:
            query: Search query string.
            limit: Maximum results to return.
            filters: Optional filters (scope_id, entity_type, etc).

        Returns:
            [(entity_id, score), ...] sorted by relevance descending.
        """
        if not query or not query.strip():
            return []

        filters = filters or {}
        where_clauses = []
        where_params = []

        # Apply filters
        if "scope_id" in filters:
            where_clauses.append("e.scope_id = ?")
            where_params.append(filters["scope_id"])

        if "entity_type" in filters:
            where_clauses.append("e.type = ?")
            where_params.append(filters["entity_type"])

        if "source_channel" in filters:
            where_clauses.append("e.source_channel = ?")
            where_params.append(filters["source_channel"])

        # Build the search query
        if self.fts_ready:
            results = self._fts_search(query, where_clauses, where_params, limit)
        else:
            results = self._like_fallback(query, where_clauses, where_params, limit)

        # Apply title boost
        results = self._apply_title_boost(query, results)

        return results

    def _fts_search(
        self,
        query: str,
        where_clauses: List[str],
        where_params: List[Any],
        limit: int,
    ) -> List[Tuple[str, float]]:
        """Search using FTS5 with BM25 ranking."""
        match_expr = build_match_term(query)

        if not match_expr:
            return []

        clauses = ["entity_fts MATCH ?"]
        params = [match_expr]
        clauses.extend(where_clauses)
        params.extend(where_params)

        where_sql = " AND ".join(clauses)
        sql = f"""
            SELECT e.id, e.name, bm25(entity_fts) as bm25_score
            FROM entity_fts
            JOIN entities e ON e.rowid = entity_fts.rowid
            WHERE {where_sql}
            ORDER BY bm25(entity_fts) ASC
            LIMIT ?
        """
        params.append(limit)

        try:
            rows = self.conn.execute(sql, params).fetchall()
            # BM25 returns lower scores for better matches, so we invert
            return [(row["id"], 1.0 / (1.0 + row["bm25_score"])) for row in rows]
        except sqlite3.Error as e:
            logger.warning(f"FTS search failed: {e}")
            return []

    def _like_fallback(
        self,
        query: str,
        where_clauses: List[str],
        where_params: List[Any],
        limit: int,
    ) -> List[Tuple[str, float]]:
        """Fallback LIKE search when FTS5 is unavailable."""
        pattern = f"%{query}%"

        clauses = ["(e.name LIKE ? OR e.properties LIKE ?)"]
        params = [pattern, pattern]
        clauses.extend(where_clauses)
        params.extend(where_params)

        where_sql = " AND ".join(clauses)
        sql = f"""
            SELECT e.id
            FROM entities e
            WHERE {where_sql}
            LIMIT ?
        """
        params.append(limit)

        try:
            rows = self.conn.execute(sql, params).fetchall()
            # Uniform scores for LIKE fallback
            return [(row["id"], 0.5) for row in rows]
        except sqlite3.Error as e:
            logger.warning(f"LIKE fallback failed: {e}")
            return []

    def _apply_title_boost(
        self, query: str, results: List[Tuple[str, float]]
    ) -> List[Tuple[str, float]]:
        """Apply title boost for exact or near-exact title matches."""
        if not results:
            return results

        query_lower = query.lower().strip()

        # Fetch entity names
        entity_ids = [eid for eid, _ in results]
        placeholders = ",".join("?" * len(entity_ids))

        rows = self.conn.execute(
            f"""
            SELECT id, name FROM entities
            WHERE id IN ({placeholders})
            """,
            entity_ids,
        ).fetchall()

        name_map = {row["id"]: row["name"] for row in rows}

        boosted_results = []
        for entity_id, score in results:
            name = name_map.get(entity_id, "")
            name_lower = name.lower() if name else ""

            # Exact title match gets highest boost
            if name_lower == query_lower:
                boosted_results.append((entity_id, score * 2.0))
            # Prefix match gets medium boost
            elif name_lower.startswith(query_lower):
                boosted_results.append((entity_id, score * 1.5))
            # Contains query gets small boost
            elif query_lower in name_lower:
                boosted_results.append((entity_id, score * 1.2))
            else:
                boosted_results.append((entity_id, score))

        # Re-sort by boosted scores
        return sorted(boosted_results, key=lambda x: x[1], reverse=True)

    def alias_hop_search(
        self, entity_id: str, limit: int = 5
    ) -> List[Tuple[str, float]]:
        """Follow entity aliases to find related entities.

        For named entities that may have multiple names/aliases.
        """
        # Check if entity has aliases in properties
        row = self.conn.execute(
            "SELECT properties FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()

        if not row or not row["properties"]:
            return []

        import json

        props = json.loads(row["properties"])
        aliases = props.get("aliases", [])

        if not aliases:
            return []

        # Search for entities with matching aliases
        results = []
        for alias in aliases[:limit]:
            alias_results = self.search(alias, limit=3)
            results.extend(alias_results)

        return results

    def close(self):
        """Close database connection."""
        self.conn.close()

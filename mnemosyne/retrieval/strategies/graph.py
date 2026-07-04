"""
Graph traversal search strategy.

Provides neighborhood-based retrieval:
- Direct neighbor lookup
- Multi-hop traversal
- Relation type filtering
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

logger = logging.getLogger(__name__)


class GraphStrategy:
    """Graph traversal search strategy."""

    def __init__(self, db_path: Path):
        """Initialize graph strategy.

        Args:
            db_path: Path to SQLite database.
        """
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(
            str(self.db_path), timeout=30.0, check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row

    def search(
        self,
        query: str,
        limit: int = 30,
        filters: Optional[Dict] = None,
    ) -> List[Tuple[str, float]]:
        """Search by graph traversal.

        For entity queries, this finds:
        1. Direct neighbors of matching entities
        2. Entities with similar connection patterns

        Args:
            query: Search query (typically entity name).
            limit: Maximum results to return.
            filters: Optional filters (relation_type, hop_depth).

        Returns:
            [(entity_id, score), ...] sorted by relevance.
        """
        if not query or not query.strip():
            return []

        filters = filters or {}
        hop_depth = filters.get("hop_depth", 1)
        relation_types = filters.get("relation_types")

        # First, find seed entities matching the query
        seed_entities = self._find_seed_entities(query, limit=5)

        if not seed_entities:
            return []

        # Expand to neighbors
        neighbors = self._get_neighbors(
            [e for e, _ in seed_entities],
            hop_depth=hop_depth,
            relation_types=relation_types,
        )

        # Score by proximity and connection strength
        results = self._score_neighbors(neighbors, seed_entities)

        return results[:limit]

    def _find_seed_entities(
        self, query: str, limit: int = 5
    ) -> List[Tuple[str, float]]:
        """Find seed entities by name/prefix matching."""
        pattern = f"%{query}%"

        rows = self.conn.execute(
            """
            SELECT id, name FROM entities
            WHERE name LIKE ? OR id LIKE ?
            LIMIT ?
            """,
            (pattern, pattern, limit),
        ).fetchall()

        # Score by name similarity
        results = []
        query_lower = query.lower()

        for row in rows:
            name = row["name"] or ""
            name_lower = name.lower()

            if name_lower == query_lower:
                score = 1.0
            elif name_lower.startswith(query_lower):
                score = 0.8
            elif query_lower in name_lower:
                score = 0.6
            else:
                score = 0.4

            results.append((row["id"], score))

        return sorted(results, key=lambda x: x[1], reverse=True)

    def _get_neighbors(
        self,
        entity_ids: List[str],
        hop_depth: int = 1,
        relation_types: Optional[List[str]] = None,
    ) -> Dict[str, Set[Tuple[str, str]]]:
        """Get neighbors within hop depth.

        Returns:
            {entity_id: {(neighbor_id, relation_type), ...}}
        """
        neighbors: Dict[str, Set[Tuple[str, str]]] = {
            eid: set() for eid in entity_ids
        }

        current_hop = set(entity_ids)

        for hop in range(hop_depth):
            next_hop: Set[str] = set()

            for entity_id in current_hop:
                # Outgoing relations
                outgoing = self._get_relations(
                    entity_id, "source", relation_types
                )

                # Incoming relations
                incoming = self._get_relations(
                    entity_id, "target", relation_types
                )

                all_relations = outgoing + incoming

                for neighbor_id, rel_type in all_relations:
                    if entity_id in neighbors:
                        neighbors[entity_id].add((neighbor_id, rel_type))
                    next_hop.add(neighbor_id)

            current_hop = next_hop

            if not current_hop:
                break

        return neighbors

    def _get_relations(
        self,
        entity_id: str,
        direction: str,
        relation_types: Optional[List[str]] = None,
    ) -> List[Tuple[str, str]]:
        """Get relations for an entity.

        Args:
            entity_id: Entity to query.
            direction: 'source' for outgoing, 'target' for incoming.
            relation_types: Optional filter by relation type.

        Returns:
            [(related_entity_id, relation_type), ...]
        """
        if direction == "source":
            sql = """
                SELECT target_id, relation_type
                FROM relations
                WHERE source_id = ?
            """
            params = [entity_id]
        else:
            sql = """
                SELECT source_id, relation_type
                FROM relations
                WHERE target_id = ?
            """
            params = [entity_id]

        if relation_types:
            placeholders = ",".join("?" * len(relation_types))
            sql += f" AND relation_type IN ({placeholders})"
            params.extend(relation_types)

        try:
            rows = self.conn.execute(sql, params).fetchall()

            if direction == "source":
                return [(row["target_id"], row["relation_type"]) for row in rows]
            else:
                return [(row["source_id"], row["relation_type"]) for row in rows]
        except sqlite3.Error as e:
            logger.warning(f"Failed to get relations: {e}")
            return []

    def _score_neighbors(
        self,
        neighbors: Dict[str, Set[Tuple[str, str]]],
        seed_entities: List[Tuple[str, float]],
    ) -> List[Tuple[str, float]]:
        """Score neighbors by proximity to seed entities.

        Args:
            neighbors: {entity_id: {(neighbor_id, relation_type), ...}}
            seed_entities: [(entity_id, seed_score), ...]

        Returns:
            [(entity_id, combined_score), ...]
        """
        entity_scores: Dict[str, float] = {}
        seen: Set[str] = set()

        # Include seed entities themselves
        for entity_id, score in seed_entities:
            entity_scores[entity_id] = max(entity_scores.get(entity_id, 0), score)
            seen.add(entity_id)

        # Score neighbors
        for entity_id, connections in neighbors.items():
            # Get seed score for this entity
            seed_score = dict(seed_entities).get(entity_id, 0.0)

            for neighbor_id, relation_type in connections:
                if neighbor_id in seen:
                    continue

                # Base score decays with hop distance
                base_score = seed_score * 0.5

                # Boost by relation type importance
                relation_boost = self._get_relation_boost(relation_type)

                entity_scores[neighbor_id] = max(
                    entity_scores.get(neighbor_id, 0),
                    base_score + relation_boost,
                )
                seen.add(neighbor_id)

        return sorted(entity_scores.items(), key=lambda x: x[1], reverse=True)

    def _get_relation_boost(self, relation_type: str) -> float:
        """Get importance boost for a relation type.

        Certain relations are more important for retrieval:
        - Direct connections: high boost
        - Weak associations: low boost
        """
        important_relations = {
            "defines", "implements", "extends", "owns", "employs",
            "founded", "created", "authored",
        }

        medium_relations = {
            "related_to", "connects_to", "references", "mentions",
        }

        if relation_type in important_relations:
            return 0.3
        elif relation_type in medium_relations:
            return 0.15
        else:
            return 0.1

    def get_connection_strength(
        self, entity_a: str, entity_b: str
    ) -> float:
        """Get connection strength between two entities.

        Returns a score from 0.0 to 1.0 based on:
        - Number of direct relations
        - Relation types
        - Shared neighbors
        """
        # Count direct relations
        direct_relations = 0

        rows = self.conn.execute(
            """
            SELECT COUNT(*) as count
            FROM relations
            WHERE (source_id = ? AND target_id = ?)
               OR (source_id = ? AND target_id = ?)
            """,
            (entity_a, entity_b, entity_b, entity_a),
        ).fetchone()

        direct_relations = rows["count"]

        # Shared neighbors (Jaccard index)
        neighbors_a = set(self._get_relations(entity_a, "source", None))
        neighbors_b = set(self._get_relations(entity_b, "source", None))

        if not neighbors_a or not neighbors_b:
            jaccard = 0.0
        else:
            intersection = len(neighbors_a & neighbors_b)
            union = len(neighbors_a | neighbors_b)
            jaccard = intersection / union if union > 0 else 0.0

        # Combine metrics
        strength = (direct_relations * 0.7) + (jaccard * 0.3)

        return min(strength, 1.0)

    def close(self):
        """Close database connection."""
        self.conn.close()

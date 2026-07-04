"""
Bi-temporal facts storage.

Implements GBrain's facts table with validity windows and time-travel queries.
"""

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class Fact:
    """Bi-temporal fact representation."""

    fact_id: str
    entity_id: str
    dimension: str  # e.g., 'role', 'status', 'location'
    value: Any
    value_type: str = "string"  # string, number, datetime, boolean
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None  # NULL means currently valid
    source_page: Optional[str] = None
    confidence: float = 1.0
    superseded_by: Optional[str] = None
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert fact to dictionary."""
        return {
            "fact_id": self.fact_id,
            "entity_id": self.entity_id,
            "dimension": self.dimension,
            "value": self.value,
            "value_type": self.value_type,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "source_page": self.source_page,
            "confidence": self.confidence,
            "superseded_by": self.superseded_by,
            "created_at": self.created_at,
        }

    def is_valid_at(self, timestamp: datetime) -> bool:
        """Check if fact is valid at given timestamp."""
        if not self.valid_from:
            return True

        valid_from_dt = datetime.fromisoformat(self.valid_from)
        if timestamp < valid_from_dt:
            return False

        if self.valid_to:
            valid_to_dt = datetime.fromisoformat(self.valid_to)
            if timestamp >= valid_to_dt:
                return False

        return True


class FactsStore:
    """Bi-temporal facts storage."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize facts store.

        Args:
            db_path: Path to SQLite database.
                Uses default if None.
        """
        if db_path is None:
            db_path = Path.home() / "mnemosyne" / "graph" / "knowledge.db"

        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(
            str(self.db_path), timeout=30.0, check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row

        self._init_schema()

    def _init_schema(self):
        """Initialize facts schema."""
        cursor = self.conn.cursor()

        # Facts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                fact_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                dimension TEXT NOT NULL,
                value TEXT NOT NULL,
                value_type TEXT DEFAULT 'string',
                valid_from TEXT NOT NULL,
                valid_to TEXT,
                source_page TEXT,
                confidence REAL DEFAULT 1.0,
                superseded_by TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (entity_id) REFERENCES entities(entity_id),
                FOREIGN KEY (superseded_by) REFERENCES facts(fact_id)
            )
        """)

        # Indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_facts_entity
            ON facts(entity_id, valid_from)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_facts_dimension
            ON facts(dimension, value)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_facts_superseded
            ON facts(superseded_by)
        """)

        self.conn.commit()

    def add_fact(
        self,
        entity_id: str,
        dimension: str,
        value: Any,
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
        confidence: float = 1.0,
        source_page: Optional[str] = None,
    ) -> str:
        """Add a new fact (supersedes existing facts for this dimension).

        Args:
            entity_id: Entity the fact applies to.
            dimension: Fact dimension (e.g., 'role', 'status').
            value: Fact value.
            valid_from: When fact becomes valid (defaults to now).
            valid_to: When fact expires (NULL = currently valid).
            confidence: Confidence score (0-1).
            source_page: Source of the fact.

        Returns:
            New fact ID.
        """
        # Serialize value
        value_str = json.dumps(value) if not isinstance(value, str) else value
        value_type = self._infer_type(value)

        # Default valid_from to now
        if valid_from is None:
            valid_from = datetime.now()

        # Find existing facts for this dimension
        existing = self._get_current_facts(entity_id, dimension)

        cursor = self.conn.cursor()

        # Supersede existing facts
        superseded_ids = []
        for old_fact in existing:
            # Mark old fact as superseded
            cursor.execute(
                """
                UPDATE facts
                SET valid_to = ?
                WHERE fact_id = ?
                """,
                (valid_from.isoformat(), old_fact.fact_id),
            )
            superseded_ids.append(old_fact.fact_id)

        # Create new fact
        fact_id = f"fact_{uuid.uuid4().hex}"

        cursor.execute(
            """
            INSERT INTO facts
            (fact_id, entity_id, dimension, value, value_type, valid_from, valid_to, source_page, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                entity_id,
                dimension,
                value_str,
                value_type,
                valid_from.isoformat(),
                valid_to.isoformat() if valid_to else None,
                source_page,
                confidence,
            ),
        )

        # Link superseded facts
        for old_id in superseded_ids:
            cursor.execute(
                """
                UPDATE facts
                SET superseded_by = ?
                WHERE fact_id = ?
                """,
                (fact_id, old_id),
            )

        self.conn.commit()

        logger.debug(
            f"Added fact {fact_id} for {entity_id}.{dimension} (superseded {len(superseded_ids)} old facts)"
        )
        return fact_id

    def get_facts(
        self,
        entity_id: str,
        dimension: Optional[str] = None,
        as_of: Optional[datetime] = None,
    ) -> List[Fact]:
        """Get facts for entity, optionally as of a point in time.

        Args:
            entity_id: Entity to query.
            dimension: Optional dimension filter.
            as_of: Query point in time (None = current).

        Returns:
            List of valid facts.
        """
        cursor = self.conn.cursor()

        conditions = ["entity_id = ?"]
        params = [entity_id]

        if dimension:
            conditions.append("dimension = ?")
            params.append(dimension)

        if as_of:
            conditions.append("valid_from <= ?")
            conditions.append("(valid_to IS NULL OR valid_to > ?)")
            params.extend([as_of.isoformat(), as_of.isoformat()])
        else:
            # Current facts: no valid_to or valid_to in future
            now = datetime.now().isoformat()
            conditions.append("valid_from <= ?")
            conditions.append("(valid_to IS NULL OR valid_to > ?)")
            params.extend([now, now])

        where = " AND ".join(conditions)

        cursor.execute(
            f"""
            SELECT * FROM facts
            WHERE {where}
            ORDER BY dimension, valid_from DESC
            """,
            params,
        )

        facts = []
        for row in cursor.fetchall():
            facts.append(
                Fact(
                    fact_id=row["fact_id"],
                    entity_id=row["entity_id"],
                    dimension=row["dimension"],
                    value=json.loads(row["value"]) if self._is_json(row["value"]) else row["value"],
                    value_type=row["value_type"],
                    valid_from=row["valid_from"],
                    valid_to=row["valid_to"],
                    source_page=row["source_page"],
                    confidence=row["confidence"],
                    superseded_by=row["superseded_by"],
                    created_at=row["created_at"],
                )
            )

        return facts

    def get_history(
        self,
        entity_id: str,
        dimension: Optional[str] = None,
    ) -> List[Fact]:
        """Get full history of facts for entity.

        Args:
            entity_id: Entity to query.
            dimension: Optional dimension filter.

        Returns:
            All facts including superseded ones.
        """
        cursor = self.conn.cursor()

        conditions = ["entity_id = ?"]
        params = [entity_id]

        if dimension:
            conditions.append("dimension = ?")
            params.append(dimension)

        where = " AND ".join(conditions)

        cursor.execute(
            f"""
            SELECT * FROM facts
            WHERE {where}
            ORDER BY dimension, valid_from ASC
            """,
            params,
        )

        facts = []
        for row in cursor.fetchall():
            facts.append(
                Fact(
                    fact_id=row["fact_id"],
                    entity_id=row["entity_id"],
                    dimension=row["dimension"],
                    value=json.loads(row["value"]) if self._is_json(row["value"]) else row["value"],
                    value_type=row["value_type"],
                    valid_from=row["valid_from"],
                    valid_to=row["valid_to"],
                    source_page=row["source_page"],
                    confidence=row["confidence"],
                    superseded_by=row["superseded_by"],
                    created_at=row["created_at"],
                )
            )

        return facts

    def find_contradictions(
        self, entity_id: Optional[str] = None, dimension: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Find conflicting facts (same dimension, different values).

        Args:
            entity_id: Optional entity filter.
            dimension: Optional dimension filter.

        Returns:
            List of contradiction groups.
        """
        cursor = self.conn.cursor()

        conditions = ["f1.valid_to IS NULL", "f2.valid_to IS NULL", "f1.value != f2.value"]
        params = []

        if entity_id:
            conditions.append("f1.entity_id = ?")
            params.append(entity_id)

        if dimension:
            conditions.append("f1.dimension = ?")
            params.append(dimension)

        where = " AND ".join(conditions)

        cursor.execute(
            f"""
            SELECT
                f1.entity_id,
                f1.dimension,
                f1.value as value1,
                f2.value as value2,
                f1.fact_id as fact_id1,
                f2.fact_id as fact_id2
            FROM facts f1
            JOIN facts f2 ON f1.entity_id = f2.entity_id AND f1.dimension = f2.dimension
            WHERE {where}
            """,
            params,
        )

        contradictions = []
        for row in cursor.fetchall():
            contradictions.append(
                {
                    "entity_id": row["entity_id"],
                    "dimension": row["dimension"],
                    "values": [row["value1"], row["value2"]],
                    "fact_ids": [row["fact_id1"], row["fact_id2"]],
                }
            )

        return contradictions

    def _get_current_facts(self, entity_id: str, dimension: str) -> List[Fact]:
        """Get currently valid facts for dimension."""
        return self.get_facts(entity_id, dimension, as_of=None)

    @staticmethod
    def _infer_type(value: Any) -> str:
        """Infer value type."""
        if isinstance(value, bool):
            return "boolean"
        elif isinstance(value, (int, float)):
            return "number"
        elif isinstance(value, datetime):
            return "datetime"
        else:
            return "string"

    @staticmethod
    def _is_json(value: str) -> bool:
        """Check if string is JSON."""
        try:
            json.loads(value)
            return True
        except (ValueError, TypeError):
            return False

    def get_fact(self, fact_id: str) -> Optional[Fact]:
        """Get fact by ID.

        Args:
            fact_id: Fact to retrieve.

        Returns:
            Fact or None.
        """
        cursor = self.conn.cursor()
        row = cursor.execute(
            "SELECT * FROM facts WHERE fact_id = ?", (fact_id,)
        ).fetchone()

        if not row:
            return None

        return Fact(
            fact_id=row["fact_id"],
            entity_id=row["entity_id"],
            dimension=row["dimension"],
            value=json.loads(row["value"]) if self._is_json(row["value"]) else row["value"],
            value_type=row["value_type"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            source_page=row["source_page"],
            confidence=row["confidence"],
            superseded_by=row["superseded_by"],
            created_at=row["created_at"],
        )

    def delete_fact(self, fact_id: str) -> bool:
        """Delete a fact.

        Args:
            fact_id: Fact to delete.

        Returns:
            True if deleted, False otherwise.
        """
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM facts WHERE fact_id = ?", (fact_id,))
        self.conn.commit()

        return cursor.rowcount > 0

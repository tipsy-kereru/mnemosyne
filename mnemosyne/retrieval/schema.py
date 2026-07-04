"""
Database schema extensions for hybrid search.

Provides migration utilities for:
- Embeddings table
- Search cache table
- Auxiliary columns on entities_fts
"""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class HybridSearchSchema:
    """Schema manager for hybrid search features."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize schema manager.

        Args:
            db_path: Path to SQLite database.
        """
        if db_path is None:
            db_path = Path.home() / "mnemosyne" / "graph" / "knowledge.db"

        self.db_path = Path(db_path)

    def migrate(self, conn: Optional[sqlite3.Connection] = None) -> bool:
        """Run all hybrid search migrations.

        Args:
            conn: Existing connection (creates new if None).

        Returns:
            True if successful, False otherwise.
        """
        close_on_exit = conn is None

        try:
            if conn is None:
                conn = sqlite3.connect(
                    str(self.db_path), timeout=30.0
                )
                conn.row_factory = sqlite3.Row

            # Run migrations
            self._create_embeddings_table(conn)
            self._create_search_cache_table(conn)
            self._create_indexes(conn)

            if close_on_exit:
                conn.commit()
                conn.close()

            logger.info("Hybrid search schema migration complete")
            return True

        except sqlite3.Error as e:
            logger.error(f"Schema migration failed: {e}")
            if close_on_exit and conn:
                conn.close()
            return False

    def _create_embeddings_table(self, conn: sqlite3.Connection) -> None:
        """Create embeddings table."""
        cursor = conn.cursor()

        # Check if table exists
        existing = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='embeddings'"
        ).fetchone()

        if not existing:
            cursor.execute("""
                CREATE TABLE embeddings (
                    entity_id TEXT PRIMARY KEY,
                    vector BLOB NOT NULL,
                    model TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    embedded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE
                )
            """)
            logger.info("Created embeddings table")
        else:
            # Check for new columns
            cursor.execute("PRAGMA table_info(embeddings)")
            columns = {row["name"] for row in cursor.fetchall()}

            if "dimension" not in columns:
                cursor.execute("ALTER TABLE embeddings ADD COLUMN dimension INTEGER")
                logger.info("Added dimension column to embeddings")

    def _create_search_cache_table(self, conn: sqlite3.Connection) -> None:
        """Create search cache table."""
        cursor = conn.cursor()

        existing = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='search_cache'"
        ).fetchone()

        if not existing:
            cursor.execute("""
                CREATE TABLE search_cache (
                    cache_key TEXT PRIMARY KEY,
                    results TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    hits INTEGER DEFAULT 0,
                    expires_at TIMESTAMP
                )
            """)
            logger.info("Created search_cache table")

    def _create_indexes(self, conn: sqlite3.Connection) -> None:
        """Create performance indexes."""
        cursor = conn.cursor()

        # Embeddings indexes
        indexes = [
            ("idx_embeddings_model", "CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model, embedded_at)"),
            ("idx_search_cache_expires", "CREATE INDEX IF NOT EXISTS idx_search_cache_expires ON search_cache(expires_at)"),
            ("idx_search_cache_created", "CREATE INDEX IF NOT EXISTS idx_search_cache_created ON search_cache(created_at)"),
        ]

        for name, sql in indexes:
            try:
                cursor.execute(sql)
                logger.debug(f"Ensured index: {name}")
            except sqlite3.Error as e:
                logger.warning(f"Failed to create index {name}: {e}")

    def get_version(self, conn: Optional[sqlite3.Connection] = None) -> int:
        """Get current schema version.

        Returns:
            Version number (0 if not initialized).
        """
        try:
            close_on_exit = conn is None

            if conn is None:
                conn = sqlite3.connect(str(self.db_path), timeout=30.0)

            cursor = conn.cursor()

            # Check for key tables
            embeddings_exists = cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='embeddings'"
            ).fetchone() is not None

            cache_exists = cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='search_cache'"
            ).fetchone() is not None

            if close_on_exit:
                conn.close()

            # Version based on features present
            version = 0
            if embeddings_exists:
                version += 1
            if cache_exists:
                version += 1

            return version

        except sqlite3.Error:
            return 0


def ensure_schema(db_path: Optional[Path] = None) -> bool:
    """Ensure hybrid search schema is initialized.

    Convenience function for quick schema setup.

    Args:
        db_path: Path to SQLite database.

    Returns:
        True if schema is ready, False otherwise.
    """
    schema = HybridSearchSchema(db_path)
    return schema.migrate()

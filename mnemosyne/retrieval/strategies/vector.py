"""
Vector similarity search strategy.

Provides semantic search using embeddings:
- Local models via sentence-transformers
- Cosine similarity computation
- Optional OpenAI embeddings
"""

import io
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# Embedding model specifications
MODEL_DIMENSIONS = {
    "all-MiniLM-L6-v2": 384,
    "all-mpnet-base-v2": 768,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}

DEFAULT_MODEL = "all-MiniLM-L6-v2"


class VectorStrategy:
    """Vector similarity search using embeddings."""

    def __init__(
        self,
        db_path: Path,
        model_name: str = DEFAULT_MODEL,
        embedding_dim: Optional[int] = None,
    ):
        """Initialize vector strategy.

        Args:
            db_path: Path to SQLite database.
            model_name: Name of embedding model.
            embedding_dim: Explicit dimension (auto-detected if None).
        """
        self.db_path = Path(db_path)
        self.model_name = model_name
        self.embedding_dim = embedding_dim or MODEL_DIMENSIONS.get(model_name, 384)

        # Initialize database connection
        self.conn = sqlite3.connect(
            str(self.db_path), timeout=30.0, check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row

        # Lazy-load the embedding model
        self._model = None

    @property
    def model(self):
        """Lazy-load sentence-transformers model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
                logger.info(f"Loaded embedding model: {self.model_name}")
            except ImportError:
                logger.warning(
                    "sentence-transformers not available. "
                    "Install with: pip install sentence-transformers"
                )
                self._model = False
        return self._model if self._model is not False else None

    def search(
        self,
        query: str,
        limit: int = 30,
        filters: Optional[Dict] = None,
    ) -> List[Tuple[str, float]]:
        """Search by vector similarity.

        Args:
            query: Search query string.
            limit: Maximum results to return.
            filters: Optional entity type filters.

        Returns:
            [(entity_id, similarity_score), ...] sorted by similarity.
        """
        if not query or not query.strip():
            return []

        # 1. Embed query
        query_embedding = self._embed(query)
        if query_embedding is None:
            return []

        # 2. Fetch candidate embeddings
        candidates = self._fetch_candidates(filters)

        if not candidates:
            logger.debug("No embeddings found in database")
            return []

        # 3. Compute cosine similarity
        scores = []
        for entity_id, embedding in candidates:
            similarity = self._cosine_similarity(query_embedding, embedding)
            scores.append((entity_id, similarity))

        # 4. Return top-k
        return sorted(scores, key=lambda x: x[1], reverse=True)[:limit]

    def _embed(self, text: str) -> Optional[np.ndarray]:
        """Generate embedding for text."""
        model = self.model
        if model is None:
            return None

        try:
            embedding = model.encode(text, show_progress_bar=False)
            return embedding
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")
            return None

    def _fetch_candidates(
        self, filters: Optional[Dict]
    ) -> List[Tuple[str, np.ndarray]]:
        """Fetch embeddings from database.

        Returns:
            [(entity_id, embedding_vector), ...]
        """
        where_clauses = []
        where_params = []

        # Apply filters
        if filters:
            if "entity_type" in filters:
                where_clauses.append("e.type = ?")
                where_params.append(filters["entity_type"])

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        sql = f"""
            SELECT emb.entity_id, emb.vector, emb.dimension
            FROM embeddings emb
            JOIN entities e ON emb.entity_id = e.id
            WHERE {where_sql}
        """

        try:
            rows = self.conn.execute(sql, where_params).fetchall()
            candidates = []

            for row in rows:
                entity_id = row["entity_id"]
                vector_blob = row["vector"]

                if vector_blob:
                    # Deserialize from blob
                    embedding = self._deserialize_vector(vector_blob)
                    if embedding is not None:
                        candidates.append((entity_id, embedding))

            return candidates

        except sqlite3.Error as e:
            logger.warning(f"Failed to fetch embeddings: {e}")
            return []

    def _deserialize_vector(self, blob: bytes) -> Optional[np.ndarray]:
        """Deserialize vector from binary blob."""
        try:
            # Try to load as numpy array
            return np.load(io.BytesIO(blob), allow_pickle=False)
        except Exception:
            # Try JSON fallback
            try:
                data = json.loads(blob)
                return np.array(data, dtype=np.float32)
            except Exception:
                logger.warning("Failed to deserialize embedding vector")
                return None

    def _serialize_vector(self, vector: np.ndarray) -> bytes:
        """Serialize vector to binary blob."""
        # Use numpy's binary format for efficiency
        buffer = io.BytesIO()
        np.save(buffer, vector, allow_pickle=False)
        return buffer.getvalue()

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        try:
            dot_product = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return float(dot_product / (norm_a * norm_b))
        except Exception as e:
            logger.warning(f"Cosine similarity computation failed: {e}")
            return 0.0

    def index_entity(
        self, entity_id: str, text: str, model: Optional[str] = None
    ) -> bool:
        """Create and store embedding for an entity.

        Args:
            entity_id: Entity to index.
            text: Text content to embed.
            model: Model name (uses default if None).

        Returns:
            True if successful, False otherwise.
        """
        model_name = model or self.model_name
        embedding = self._embed(text)

        if embedding is None:
            return False

        # Serialize and store
        vector_blob = self._serialize_vector(embedding)

        cursor = self.conn.cursor()
        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO embeddings
                (entity_id, vector, model, dimension)
                VALUES (?, ?, ?, ?)
                """,
                (entity_id, vector_blob, model_name, len(embedding)),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.warning(f"Failed to store embedding: {e}")
            return False

    def batch_index(
        self, entity_texts: Dict[str, str], model: Optional[str] = None
    ) -> int:
        """Batch index multiple entities.

        Args:
            entity_texts: {entity_id: text_to_embed}
            model: Model name (uses default if None).

        Returns:
            Number of successfully indexed entities.
        """
        success_count = 0

        for entity_id, text in entity_texts.items():
            if self.index_entity(entity_id, text, model):
                success_count += 1

        logger.info(f"Batch indexed {success_count}/{len(entity_texts)} entities")
        return success_count

    def has_embeddings(self) -> bool:
        """Check if any embeddings exist in the database."""
        row = self.conn.execute("SELECT COUNT(*) as count FROM embeddings").fetchone()
        return row["count"] > 0

    def get_embedding_stats(self) -> Dict[str, Any]:
        """Get statistics about stored embeddings."""
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(DISTINCT model) as models,
                MIN(embedded_at) as oldest,
                MAX(embedded_at) as newest
            FROM embeddings
            """
        ).fetchone()

        return {
            "total_embeddings": row["total"],
            "distinct_models": row["models"],
            "oldest": row["oldest"],
            "newest": row["newest"],
        }

    def close(self):
        """Close database connection."""
        self.conn.close()

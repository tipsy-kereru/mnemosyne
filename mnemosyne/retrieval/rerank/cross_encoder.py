"""
Cross-encoder reranker for improved relevance.

Optional reranking using cross-encoder models for better
relevance estimation on top of initial retrieval results.
"""

import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """Cross-encoder based reranker.

    Uses a cross-encoder model to rerank retrieved results
    for improved relevance.

    This is an optional component that requires additional
    dependencies (sentence-transformers or similar).
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        device: Optional[str] = None,
    ):
        """Initialize cross-encoder reranker.

        Args:
            model_name: Name of cross-encoder model.
            device: Device to run on ('cuda', 'cpu', or None for auto).
        """
        self.model_name = model_name
        self.device = device
        self._model = None

    @property
    def model(self):
        """Lazy-load the cross-encoder model."""
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(
                    self.model_name, device=self.device
                )
                logger.info(f"Loaded cross-encoder model: {self.model_name}")
            except ImportError:
                logger.warning(
                    "sentence-transformers not available. "
                    "Install with: pip install sentence-transformers"
                )
                self._model = False
        return self._model if self._model is not False else None

    def rerank(
        self,
        query: str,
        results: List[Tuple[str, str, float]],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, str, float]]:
        """Rerank results using cross-encoder.

        Args:
            query: Search query.
            results: [(entity_id, entity_text, initial_score), ...]
            top_k: Number of top results to return (None for all).

        Returns:
            [(entity_id, entity_text, reranked_score), ...]
        """
        model = self.model
        if model is None:
            # Return original results if model unavailable
            return results

        if not results:
            return results

        # Prepare query-document pairs
        pairs = [[query, text] for _, text, _ in results]

        try:
            # Compute cross-encoder scores
            scores = model.predict(pairs)

            # Combine with initial scores (optional blending)
            reranked = []
            for (entity_id, text, initial_score), rerank_score in zip(
                results, scores
            ):
                # Blend scores (70% rerank, 30% initial)
                blended = 0.7 * rerank_score + 0.3 * initial_score
                reranked.append((entity_id, text, blended))

            # Sort by reranked score
            reranked.sort(key=lambda x: x[2], reverse=True)

            if top_k:
                reranked = reranked[:top_k]

            return reranked

        except Exception as e:
            logger.warning(f"Reranking failed: {e}")
            return results

    def rerank_simple(
        self,
        query: str,
        entity_texts: List[Tuple[str, str]],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, float]]:
        """Simple reranking interface.

        Args:
            query: Search query.
            entity_texts: [(entity_id, entity_text), ...]
            top_k: Number of top results to return.

        Returns:
            [(entity_id, reranked_score), ...]
        """
        # Add dummy initial scores
        with_scores = [(eid, text, 0.5) for eid, text in entity_texts]

        reranked = self.rerank(query, with_scores, top_k)

        return [(eid, score) for eid, _, score in reranked]

    def is_available(self) -> bool:
        """Check if cross-encoder model is available."""
        return self.model is not None

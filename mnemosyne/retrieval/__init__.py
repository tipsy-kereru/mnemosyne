"""
Hybrid search retrieval system for Mnemosyne.

Implements GBrain-inspired multi-strategy search with:
- RRF (Reciprocal Rank Fusion) for result merging
- Vector similarity search
- Enhanced BM25 keyword search
- Graph traversal augmentation
- Optional cross-encoder reranking
"""

from mnemosyne.retrieval.engine import RetrievalEngine, SearchMode, SearchResult

__all__ = [
    "RetrievalEngine",
    "SearchMode",
    "SearchResult",
]

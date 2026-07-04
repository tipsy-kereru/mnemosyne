"""
Search strategies for hybrid retrieval.

Each strategy implements a search interface returning:
    List[Tuple[str, float]]  # (entity_id, score)

Strategies are executed in parallel and results fused via RRF.
"""

from mnemosyne.retrieval.strategies.vector import VectorStrategy
from mnemosyne.retrieval.strategies.bm25 import BM25Strategy
from mnemosyne.retrieval.strategies.graph import GraphStrategy
from mnemosyne.retrieval.strategies.fusion import rrf_fusion, fused_scores_with_evidence

__all__ = [
    "VectorStrategy",
    "BM25Strategy",
    "GraphStrategy",
    "rrf_fusion",
    "fused_scores_with_evidence",
]

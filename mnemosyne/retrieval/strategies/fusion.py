"""
Reciprocal Rank Fusion (RRF) implementation.

RRF is a simple, effective method for combining ranked lists from
multiple retrieval strategies without global weighting.

Formula: score = sum(1 / (k + rank))

Where k is a constant (typically 60) that prevents the first result
from dominating the fused score.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


def rrf_fusion(
    strategy_results: Dict[str, List[Tuple[str, float]]],
    k: int = 60,
    limit: int = 100,
) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion of multiple strategy results.

    Args:
        strategy_results: {strategy_name: [(entity_id, raw_score), ...]}
        k: RRF constant (default 60). Higher values reduce the impact of
           early ranks, making the fusion more balanced.
        limit: Maximum number of results to return.

    Returns:
        [(entity_id, fused_score), ...] sorted by fused_score descending.
    """
    fused_scores: Dict[str, float] = defaultdict(float)

    for strategy_name, results in strategy_results.items():
        for rank, (entity_id, raw_score) in enumerate(results, start=1):
            # RRF formula: 1 / (k + rank)
            fused_scores[entity_id] += 1.0 / (k + rank)

            logger.debug(
                f"{strategy_name}: {entity_id} rank={rank} "
                f"contribution={1.0/(k+rank):.4f}"
            )

    # Sort by fused score descending
    sorted_results = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

    return sorted_results[:limit]


def fused_scores_with_evidence(
    strategy_results: Dict[str, List[Tuple[str, float]]],
    k: int = 60,
    limit: int = 100,
) -> List[Tuple[str, float, Dict[str, List[str]]]]:
    """RRF fusion with evidence tracking.

    Args:
        strategy_results: {strategy_name: [(entity_id, raw_score), ...]}
        k: RRF constant (default 60).
        limit: Maximum number of results to return.

    Returns:
        [(entity_id, fused_score, evidence_dict), ...]
        where evidence_dict tracks which strategies contributed.
    """
    fused_scores: Dict[str, float] = defaultdict(float)
    evidence: Dict[str, Dict[str, List[str]]] = defaultdict(
        lambda: {"strategies": [], "ranks": {}}
    )

    for strategy_name, results in strategy_results.items():
        for rank, (entity_id, raw_score) in enumerate(results, start=1):
            contribution = 1.0 / (k + rank)
            fused_scores[entity_id] += contribution

            # Track evidence
            evidence[entity_id]["strategies"].append(strategy_name)
            evidence[entity_id]["ranks"][strategy_name] = rank

    # Sort by fused score descending
    sorted_results = sorted(
        fused_scores.items(), key=lambda x: x[1], reverse=True
    )[:limit]

    # Attach evidence to results
    results_with_evidence = []
    for entity_id, score in sorted_results:
        results_with_evidence.append((entity_id, score, dict(evidence[entity_id])))

    return results_with_evidence


def normalize_scores(
    results: List[Tuple[str, float]],
    method: str = "minmax",
) -> List[Tuple[str, float]]:
    """Normalize scores to [0, 1] range.

    Args:
        results: [(entity_id, raw_score), ...]
        method: Normalization method ('minmax' or 'softmax')

    Returns:
        [(entity_id, normalized_score), ...]
    """
    if not results:
        return []

    scores = [score for _, score in results]
    entity_ids = [eid for eid, _ in results]

    if method == "minmax":
        min_score = min(scores)
        max_score = max(scores)
        range_val = max_score - min_score

        if range_val == 0:
            # All scores are the same
            normalized = [0.5] * len(scores)
        else:
            normalized = [(s - min_score) / range_val for s in scores]

    elif method == "softmax":
        import numpy as np

        exp_scores = np.exp(np.array(scores) - max(scores))  # Stable softmax
        normalized = (exp_scores / exp_scores.sum()).tolist()

    else:
        raise ValueError(f"Unknown normalization method: {method}")

    return list(zip(entity_ids, normalized))


def weighted_fusion(
    strategy_results: Dict[str, List[Tuple[str, float]]],
    weights: Dict[str, float],
    limit: int = 100,
) -> List[Tuple[str, float]]:
    """Weighted fusion of ranked results.

    Args:
        strategy_results: {strategy_name: [(entity_id, raw_score), ...]}
        weights: {strategy_name: weight} - weights should sum to 1.0
        limit: Maximum number of results to return.

    Returns:
        [(entity_id, fused_score), ...]
    """
    # Normalize weights
    total_weight = sum(weights.values())
    if total_weight == 0:
        weights = {k: 1.0 / len(weights) for k in weights}
    else:
        weights = {k: v / total_weight for k, v in weights.items()}

    fused_scores: Dict[str, float] = defaultdict(float)

    for strategy_name, results in strategy_results.items():
        weight = weights.get(strategy_name, 0.0)
        if weight == 0:
            continue

        # First normalize scores within this strategy
        normalized = normalize_scores(results, method="minmax")

        for entity_id, norm_score in normalized:
            fused_scores[entity_id] += norm_score * weight

    # Sort by fused score descending
    sorted_results = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

    return sorted_results[:limit]

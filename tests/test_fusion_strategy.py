"""
Tests for RRF fusion strategy.
"""

import pytest

from mnemosyne.retrieval.strategies.fusion import (
    rrf_fusion,
    fused_scores_with_evidence,
    normalize_scores,
    weighted_fusion,
)


class TestRRFFusion:
    """Tests for Reciprocal Rank Fusion."""

    def test_single_strategy(self):
        """RRF should work with single strategy."""
        results = {
            "bm25": [("e1", 0.9), ("e2", 0.8), ("e3", 0.7)]
        }

        fused = rrf_fusion(results, k=60)

        assert len(fused) == 3
        assert [eid for eid, _ in fused] == ["e1", "e2", "e3"]

    def test_multiple_strategies(self):
        """RRF should merge multiple strategies."""
        results = {
            "bm25": [("e1", 0.9), ("e2", 0.8), ("e3", 0.7)],
            "vector": [("e3", 0.95), ("e1", 0.85), ("e4", 0.75)],
        }

        fused = rrf_fusion(results, k=60)

        # e1 appears in both, should have highest score
        assert len(fused) == 4
        entity_ids = [eid for eid, _ in fused]
        assert "e1" in entity_ids
        assert "e2" in entity_ids
        assert "e3" in entity_ids
        assert "e4" in entity_ids

        # e1 should be top (appears in both strategies)
        assert entity_ids[0] == "e1"

    def test_k_parameter_affects_scores(self):
        """Different k values should affect score distribution."""
        results = {
            "bm25": [("e1", 0.9), ("e2", 0.8)]
        }

        fused_k60 = rrf_fusion(results, k=60)
        fused_k10 = rrf_fusion(results, k=10)

        # Same ordering, different scores
        assert [eid for eid, _ in fused_k60] == [eid for eid, _ in fused_k10]

        # Lower k amplifies rank differences
        score_diff_k60 = fused_k60[0][1] - fused_k60[1][1]
        score_diff_k10 = fused_k10[0][1] - fused_k10[1][1]
        assert score_diff_k10 > score_diff_k60

    def test_limit_parameter(self):
        """Limit should restrict output size."""
        results = {
            "bm25": [("e1", 0.9), ("e2", 0.8), ("e3", 0.7)]
        }

        fused = rrf_fusion(results, limit=2)

        assert len(fused) == 2

    def test_empty_results(self):
        """Empty results should return empty list."""
        fused = rrf_fusion({})
        assert fused == []

    def test_score_ordering(self):
        """Results should be sorted by score descending."""
        results = {
            "bm25": [("e3", 0.7), ("e2", 0.8), ("e1", 0.9)]
        }

        fused = rrf_fusion(results)

        scores = [score for _, score in fused]
        assert scores == sorted(scores, reverse=True)


class TestFusedScoresWithEvidence:
    """Tests for RRF with evidence tracking."""

    def test_evidence_tracking(self):
        """Should track which strategies contributed."""
        results = {
            "bm25": [("e1", 0.9), ("e2", 0.8)],
            "vector": [("e1", 0.85), ("e3", 0.75)],
        }

        fused = fused_scores_with_evidence(results)

        assert len(fused) == 3

        # e1 should have evidence from both strategies
        e1_result = next((r for r in fused if r[0] == "e1"), None)
        assert e1_result is not None
        assert set(e1_result[2]["strategies"]) == {"bm25", "vector"}

        # e2 should only have bm25 evidence
        e2_result = next((r for r in fused if r[0] == "e2"), None)
        assert e2_result is not None
        assert e2_result[2]["strategies"] == ["bm25"]

    def test_rank_tracking(self):
        """Should track ranks from each strategy."""
        results = {
            "bm25": [("e1", 0.9), ("e2", 0.8), ("e3", 0.7)],
            "vector": [("e3", 0.95), ("e1", 0.85)],
        }

        fused = fused_scores_with_evidence(results)

        # Check e1 ranks
        e1_result = next((r for r in fused if r[0] == "e1"), None)
        assert e1_result is not None
        assert e1_result[2]["ranks"]["bm25"] == 1
        assert e1_result[2]["ranks"]["vector"] == 2


class TestNormalizeScores:
    """Tests for score normalization."""

    def test_minmax_normalization(self):
        """Minmax should scale to [0, 1]."""
        results = [("e1", 10), ("e2", 5), ("e3", 0)]

        normalized = normalize_scores(results, method="minmax")

        scores = [score for _, score in normalized]
        assert max(scores) == 1.0
        assert min(scores) == 0.0

    def test_minmax_identical_scores(self):
        """Identical scores should normalize to 0.5."""
        results = [("e1", 5), ("e2", 5), ("e3", 5)]

        normalized = normalize_scores(results, method="minmax")

        scores = [score for _, score in normalized]
        assert all(s == 0.5 for s in scores)

    def test_softmax_normalization(self):
        """Softmax should create probability distribution."""
        results = [("e1", 3), ("e2", 2), ("e3", 1)]

        normalized = normalize_scores(results, method="softmax")

        scores = [score for _, score in normalized]
        assert abs(sum(scores) - 1.0) < 0.001  # Sums to ~1
        assert all(0 <= s <= 1 for s in scores)

    def test_invalid_method(self):
        """Invalid method should raise error."""
        results = [("e1", 1)]

        with pytest.raises(ValueError):
            normalize_scores(results, method="invalid")


class TestWeightedFusion:
    """Tests for weighted fusion."""

    def test_weighted_fusion(self):
        """Should apply weights to strategies."""
        results = {
            "bm25": [("e1", 0.9), ("e2", 0.8)],
            "vector": [("e1", 0.7), ("e3", 0.6)],
        }

        weights = {"bm25": 0.7, "vector": 0.3}

        fused = weighted_fusion(results, weights)

        assert len(fused) == 3
        # Higher weight strategy should influence more

    def test_weight_normalization(self):
        """Weights should be normalized to sum to 1."""
        results = {
            "bm25": [("e1", 0.9)],
            "vector": [("e2", 0.8)],
        }

        # These don't sum to 1
        weights = {"bm25": 2.0, "vector": 1.0}

        fused = weighted_fusion(results, weights)

        # Should still work due to normalization
        assert len(fused) == 2

    def test_zero_weight_strategy(self):
        """Zero-weight strategies should be ignored."""
        results = {
            "bm25": [("e1", 0.9)],
            "vector": [("e2", 0.8)],
        }

        weights = {"bm25": 1.0, "vector": 0.0}

        fused = weighted_fusion(results, weights)

        # Only e1 should appear
        assert len(fused) == 1
        assert fused[0][0] == "e1"

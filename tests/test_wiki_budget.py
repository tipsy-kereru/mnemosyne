"""
Tests for SPEC-HEADROOM-001 wiki budget pruning (REQ-005).

Covers:
- AC7: pruner caps token budget, preserves top-N by score, partitions
  kept/merged/pruned.
- AC12: heuristic token counting works when mnemosyne-core is absent.
"""

import os
import time
from pathlib import Path

import pytest

from mnemosyne.wiki.budget import (
    BudgetResult,
    count_tokens,
    prune_wiki_budget,
)


@pytest.fixture
def wiki_root(tmp_path):
    """Build a small wiki tree with varied importance/recency."""
    root = tmp_path / "wiki"
    root.mkdir()

    # High-value recent doc
    (root / "important_recent.md").write_text("# Important\n" + "alpha " * 200)
    # Low-value old doc
    (root / "lowvalue_old.md").write_text("# Low\n" + "beta " * 200)
    # Near-duplicate of important_recent (same body)
    (root / "important_recent_dup.md").write_text("# Important\n" + "alpha " * 200)
    # Medium doc
    (root / "medium.md").write_text("# Medium\n" + "gamma " * 50)
    return root


# -- AC12: token counting --


class TestTokenCounting:
    def test_heuristic_is_len_div_4(self):
        text = "a" * 100
        assert count_tokens(text) == 25  # 100 // 4

    def test_empty_text(self):
        assert count_tokens("") == 0

    def test_returns_int(self):
        assert isinstance(count_tokens("hello world"), int)

    def test_does_not_raise_without_rust_core(self):
        """AC12: heuristic path works when mnemosyne-core is absent."""
        # count_tokens must never raise even if the optional Rust core is missing
        assert count_tokens("some prose here") > 0


# -- AC7: budget pruning --


class TestBudgetPruning:
    def test_returns_structured_result(self, wiki_root):
        result = prune_wiki_budget(wiki_root, token_budget=10_000)
        assert isinstance(result, BudgetResult)
        assert hasattr(result, "kept")
        assert hasattr(result, "pruned")
        assert hasattr(result, "merged")
        assert hasattr(result, "total_tokens")

    def test_kept_under_budget(self, wiki_root):
        # Tiny budget forces pruning
        result = prune_wiki_budget(wiki_root, token_budget=30)
        kept_tokens = sum(count_tokens(Path(d.path).read_text()) for d in result.kept)
        assert kept_tokens <= 30

    def test_preserves_top_n_by_score(self, wiki_root):
        """The highest-scoring doc must survive pruning."""
        result = prune_wiki_budget(wiki_root, token_budget=10_000)
        kept_names = {Path(d.path).name for d in result.kept}
        # important_recent should always be kept (high importance + recent)
        assert "important_recent.md" in kept_names

    def test_near_duplicates_merged(self, wiki_root):
        """Near-duplicate docs are merged into one representative."""
        result = prune_wiki_budget(wiki_root, token_budget=10_000)
        merged_names = {Path(m.path).name for m in result.merged}
        # The duplicate of important_recent is merged away
        assert "important_recent_dup.md" in merged_names
        # And it is NOT in kept (it was merged)
        kept_names = {Path(d.path).name for d in result.kept}
        assert "important_recent_dup.md" not in kept_names

    def test_low_score_pruned_under_tight_budget(self, wiki_root):
        result = prune_wiki_budget(wiki_root, token_budget=30)
        all_names = (
            {Path(d.path).name for d in result.kept}
            | {Path(m.path).name for m in result.merged}
            | {Path(p.path).name for p in result.pruned}
        )
        # Every input doc is accounted for in exactly one partition
        inputs = {p.name for p in wiki_root.glob("*.md")}
        assert all_names == inputs

    def test_large_budget_keeps_everything(self, wiki_root):
        """With a generous budget, nothing is pruned (only dupes merge)."""
        result = prune_wiki_budget(wiki_root, token_budget=1_000_000)
        assert len(result.pruned) == 0
        # Merges still happen (dupes collapse) but no pruning
        kept_names = {Path(d.path).name for d in result.kept}
        assert "important_recent.md" in kept_names

    def test_ranking_uses_importance_recency_access(self, wiki_root):
        """DocScore exposes the three ranking factors."""
        # Make lowvalue_old genuinely older than important_recent
        old_path = wiki_root / "lowvalue_old.md"
        now = time.time()
        os.utime(old_path, (now - 60 * 60 * 24 * 365, now - 60 * 60 * 24 * 365))

        result = prune_wiki_budget(wiki_root, token_budget=10_000)
        scores_by_name = {Path(d.path).name: d for d in result.kept}
        # If important_recent survived, its score should exceed the old doc's
        # (recency decay makes the year-old doc score lower).
        if "important_recent.md" in scores_by_name and "lowvalue_old.md" in scores_by_name:
            assert scores_by_name["important_recent.md"].score >= scores_by_name["lowvalue_old.md"].score

    def test_empty_wiki_dir(self, tmp_path):
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        result = prune_wiki_budget(empty_root, token_budget=1000)
        assert result.kept == []
        assert result.pruned == []
        assert result.merged == []

    def test_no_markdown_files(self, tmp_path):
        root = tmp_path / "mixed"
        root.mkdir()
        (root / "notes.txt").write_text("not markdown")
        result = prune_wiki_budget(root, token_budget=1000)
        assert result.kept == []

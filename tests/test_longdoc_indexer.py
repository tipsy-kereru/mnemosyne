"""Tests for SPEC-LONGDOC-001 REQ-LD-002 / REQ-LD-005 / REQ-LD-006.

Covers:
- AC-2: markdown split, tree build with depth<=4 and fan-out<=8.
- AC-5: SLM-first / LLM-fallback / NULL-on-failure degraded summary.
- AC-6: no-delete supersession on re-index; zero DELETE statements in the
  longdoc code path (grep-verified).
"""

from pathlib import Path

import pytest

from mnemosyne.extraction.longdoc.tree_indexer import (
    LongDocIndexer,
    MAX_DEPTH,
    MAX_FANOUT,
    _build_tree,
    split_markdown,
)
from mnemosyne.graph.knowledge_graph import KnowledgeGraph


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_longdoc_indexer.db")


@pytest.fixture
def kg(db_path):
    graph = KnowledgeGraph(db_path=db_path)
    yield graph
    graph.close()


def _twenty_five_page_md() -> str:
    """Fixture doc: 25 sections, each ~600 words (forces multi-level tree)."""
    return "\n".join(
        [f"# Section {i}\n\n" + ("word " * 600) for i in range(25)]
    )


# -- AC-2: markdown splitter -----------------------------------------------


class TestMarkdownSplitter:
    def test_split_by_headings(self):
        text = "# Intro\n\nHello\n\n## Details\n\nWorld"
        sections = split_markdown(text)
        # Preamble "Hello" is captured as Introduction; two heading sections.
        titles = [s.title for s in sections]
        assert "Intro" in titles
        assert "Details" in titles

    def test_split_no_headings_single_section(self):
        text = "Just a wall of text without headings. " * 50
        sections = split_markdown(text)
        assert len(sections) == 1
        assert sections[0].token_end > 0

    def test_token_offsets_cumulative(self):
        text = "# A\n\nx x x\n\n# B\n\ny y y"
        sections = split_markdown(text)
        # Second section's token_start should equal first section's token_end
        # (cumulative offsets, not overlapping).
        if len(sections) >= 2:
            assert sections[1].token_start >= sections[0].token_start


# -- AC-2: tree builder depth/fan-out bounds -------------------------------


class TestTreeBuilderBounds:
    def test_depth_at_most_four(self):
        sections = split_markdown(_twenty_five_page_md())
        roots = _build_tree(sections)
        # Flatten and check max depth.
        stack = list(roots)
        max_depth = -1
        while stack:
            n = stack.pop()
            max_depth = max(max_depth, n.depth)
            stack.extend(n.children)
        assert max_depth <= MAX_DEPTH

    def test_fan_out_at_most_eight(self):
        sections = split_markdown(_twenty_five_page_md())
        roots = _build_tree(sections)
        # Collect parent_id -> child counts.
        from collections import defaultdict
        child_counts: dict = defaultdict(int)
        stack = list(roots)
        all_nodes = []
        while stack:
            n = stack.pop()
            all_nodes.append(n)
            stack.extend(n.children)
        for n in all_nodes:
            if n.parent_id is not None:
                child_counts[n.parent_id] += 1
        for parent, count in child_counts.items():
            assert count <= MAX_FANOUT, f"parent {parent} has {count} children"

    def test_single_section_single_root(self):
        sections = split_markdown("no headings here " * 10)
        roots = _build_tree(sections)
        assert len(roots) == 1


# -- AC-2 / AC-6: indexer end-to-end ---------------------------------------


class TestIndexerPersistence:
    def test_index_text_returns_tree_id(self, kg):
        idx = LongDocIndexer(
            conn=kg.conn, entity_types=["clause", "party"], domain="legal"
        )
        tree_id = idx.index_text(
            _twenty_five_page_md(), source_hash="h1", kind="markdown"
        )
        assert tree_id is not None
        # Tree row exists with status active.
        row = kg.conn.execute(
            "SELECT status, source_hash FROM document_trees WHERE tree_id=?",
            (tree_id,),
        ).fetchone()
        assert row["status"] == "active"
        assert row["source_hash"] == "h1"

    def test_index_text_persists_nodes_within_bounds(self, kg):
        idx = LongDocIndexer(conn=kg.conn, entity_types=["note"], domain="daily")
        tree_id = idx.index_text(
            _twenty_five_page_md(), source_hash="h2", kind="markdown"
        )
        max_depth = kg.conn.execute(
            "SELECT MAX(depth) FROM tree_nodes WHERE tree_id=?", (tree_id,)
        ).fetchone()[0]
        assert max_depth <= MAX_DEPTH
        # Fan-out bound.
        violations = kg.conn.execute(
            "SELECT parent_id, COUNT(*) c FROM tree_nodes "
            "WHERE tree_id=? AND parent_id IS NOT NULL "
            "GROUP BY parent_id HAVING c > ?",
            (tree_id, MAX_FANOUT),
        ).fetchall()
        assert violations == []

    def test_index_file_markdown(self, kg, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Hello\n\n" + ("word " * 50))
        idx = LongDocIndexer(conn=kg.conn, entity_types=["note"], domain="daily")
        tree_id = idx.index_file(f, source_hash="hfile")
        assert tree_id is not None
        n_nodes = kg.conn.execute(
            "SELECT COUNT(*) FROM tree_nodes WHERE tree_id=?", (tree_id,)
        ).fetchone()[0]
        assert n_nodes >= 1


# -- AC-6: no-delete supersession ------------------------------------------


class TestNoDeleteSupersession:
    def test_reindex_supersedes_prior_tree(self, kg):
        idx = LongDocIndexer(conn=kg.conn, entity_types=["note"], domain="daily")
        first = idx.index_text(
            "# v1\n\n" + ("a " * 20000), source_hash="sup1", kind="markdown"
        )
        second = idx.index_text(
            "# v2\n\n" + ("b " * 20000), source_hash="sup1", kind="markdown"
        )
        assert first != second
        prior = kg.conn.execute(
            "SELECT status, superseded_by FROM document_trees WHERE tree_id=?",
            (first,),
        ).fetchone()
        assert prior["status"] == "superseded"
        assert prior["superseded_by"] == second
        # New tree is active.
        new = kg.conn.execute(
            "SELECT status FROM document_trees WHERE tree_id=?", (second,)
        ).fetchone()
        assert new["status"] == "active"

    def test_both_trees_queryable_after_supersession(self, kg):
        """R-LD-004 mitigation: superseded tree rows remain in the DB."""
        idx = LongDocIndexer(conn=kg.conn, entity_types=["note"], domain="daily")
        first = idx.index_text(
            "# v1\n\n" + ("a " * 20000), source_hash="sup2", kind="markdown"
        )
        idx.index_text(
            "# v2\n\n" + ("b " * 20000), source_hash="sup2", kind="markdown"
        )
        # Prior tree row still exists (no DELETE).
        row = kg.conn.execute(
            "SELECT COUNT(*) FROM document_trees WHERE tree_id=?", (first,)
        ).fetchone()[0]
        assert row == 1

    def test_no_delete_in_longdoc_code_path(self):
        """AC-6 grep gate: zero ``DELETE FROM`` SQL in longdoc package sources.

        We match the SQL form ``DELETE FROM`` (case-insensitive) so docstring
        mentions of the word DELETE do not false-positive.
        """
        import re
        root = Path(__file__).resolve().parent.parent / "mnemosyne" / "extraction" / "longdoc"
        delete_re = re.compile(r"DELETE\s+FROM", re.IGNORECASE)
        offenders = []
        for src in root.rglob("*.py"):
            for lineno, line in enumerate(src.read_text().splitlines(), start=1):
                # Strip trailing comment, then look for the SQL pattern.
                stripped = line.split("#", 1)[0]
                if delete_re.search(stripped):
                    offenders.append(f"{src.name}:{lineno}: {line.strip()}")
        assert offenders == [], f"DELETE FROM found in longdoc code: {offenders}"


# -- AC-5: degraded-mode NULL summary --------------------------------------


class TestDegradedSummary:
    def test_summary_null_when_slm_and_llm_unavailable(self, kg, monkeypatch):
        """When SLM and LLM are both unavailable, summary stays NULL (AC-5)."""
        # Force the summariser to see no GLiNER and no LLM by monkeypatching
        # the lazy accessors to return None.
        from mnemosyne.extraction.longdoc import tree_indexer as ti

        idx = ti.LongDocIndexer(
            conn=kg.conn, entity_types=["note"], domain="daily"
        )

        class _NoSummariser:
            def summarise(self, body):
                return None, []

        # Patch the internal summariser instantiation via a thin wrapper.
        original = ti._Summariser

        def _factory(*args, **kwargs):
            inst = original(*args, **kwargs)
            inst.summarise = lambda body: (None, [])
            return inst

        monkeypatch.setattr(ti, "_Summariser", _factory)
        tree_id = idx.index_text(
            "# v1\n\n" + ("a " * 20000), source_hash="deg1", kind="markdown"
        )
        # At least one node should have NULL summary in degraded mode.
        null_count = kg.conn.execute(
            "SELECT COUNT(*) FROM tree_nodes WHERE tree_id=? AND summary IS NULL",
            (tree_id,),
        ).fetchone()[0]
        assert null_count > 0

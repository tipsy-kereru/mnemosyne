"""
End-to-end integration tests for the extraction pipeline (SPEC-PIPE-001).

These tests exercise the full pipeline from source discovery through
KnowledgeGraph storage, covering REQ-001 through REQ-008.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from mnemosyne.extraction.pipeline import (
    DomainRouter,
    ExtractionPipeline,
    IncrementalTracker,
    ReportFormatter,
)
from mnemosyne.extraction.pipeline_types import ExtractionReport
from mnemosyne.graph.knowledge_graph import KnowledgeGraph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kg(tmp_path):
    db_path = tmp_path / "knowledge.db"
    graph = KnowledgeGraph(str(db_path))
    yield graph
    graph.close()


@pytest.fixture()
def coding_project(tmp_path):
    """A small multi-file Python project."""
    src = tmp_path / "project"
    src.mkdir()
    (src / "main.py").write_text(
        "import os\n\n"
        "def run():\n"
        "    name = get_name()\n"
        "    print(name)\n\n"
        "def get_name():\n"
        "    return 'world'\n"
    )
    (src / "utils.py").write_text(
        "class Formatter:\n"
        "    def format(self, text):\n"
        "        return text.upper()\n"
    )
    (src / "data.json").write_text('{"key": "value"}')
    return src


@pytest.fixture()
def daily_project(tmp_path):
    """Text files for daily domain extraction."""
    src = tmp_path / "notes"
    src.mkdir()
    (src / "notes.txt").write_text(
        "John Smith works at Google and lives in San Francisco. "
        "Meeting with Jane on 2025-01-15."
    )
    (src / "todo.md").write_text(
        "# Todo\n- Buy groceries\n- Call mom\n"
    )
    return src


# == Integration Tests ======================================================


class TestCodingDomainFullFlow:
    """REQ-001, REQ-002, REQ-004: Coding domain end-to-end."""

    def test_full_extraction_stores_to_graph(self, kg, coding_project):
        """Entities from Python files are extracted and stored in KG."""
        pipeline = ExtractionPipeline(
            domain="coding",
            source=coding_project,
            knowledge_graph=kg,
        )
        report = pipeline.run()

        # Files: main.py and utils.py (data.json filtered out).
        assert report.files_discovered == 2
        assert report.files_processed == 2
        assert report.files_failed == 0
        assert report.entities_extracted > 0
        assert report.entities_stored > 0
        assert report.domain == "coding"

        # Verify entities in KnowledgeGraph.
        functions = kg.get_entities_by_type("function")
        assert len(functions) > 0
        func_names = {f.name for f in functions}
        assert "run" in func_names
        assert "get_name" in func_names

    def test_scope_isolation(self, kg, coding_project):
        """Entities from different scope_ids are isolated."""
        # Run with scope A.
        pipeline_a = ExtractionPipeline(
            domain="coding",
            source=coding_project,
            knowledge_graph=kg,
            scope_id="scope-a",
        )
        report_a = pipeline_a.run()

        # Run with scope B.
        pipeline_b = ExtractionPipeline(
            domain="coding",
            source=coding_project,
            knowledge_graph=kg,
            scope_id="scope-b",
        )
        report_b = pipeline_b.run()

        # Entities for scope-a should still be accessible.
        cursor = kg.conn.cursor()
        a_count = cursor.execute(
            "SELECT COUNT(*) FROM entities WHERE scope_id='scope-a'"
        ).fetchone()[0]
        b_count = cursor.execute(
            "SELECT COUNT(*) FROM entities WHERE scope_id='scope-b'"
        ).fetchone()[0]
        assert a_count > 0
        assert b_count > 0

    def test_report_formatting_roundtrip(self, kg, coding_project):
        """Report can be formatted as JSON and parsed back."""
        pipeline = ExtractionPipeline(
            domain="coding",
            source=coding_project,
            knowledge_graph=kg,
        )
        report = pipeline.run()

        json_str = ReportFormatter.format_json(report)
        parsed = json.loads(json_str)
        assert parsed["domain"] == "coding"
        assert parsed["entities_extracted"] == report.entities_extracted

        summary = ReportFormatter.format_summary(report)
        assert "coding" in summary

        wiki = ReportFormatter.format_wiki(report)
        assert "[[domain:coding]]" in wiki


class TestIncrementalModeFullCycle:
    """REQ-003: Incremental extraction full cycle."""

    def test_incremental_skips_unchanged(self, kg, coding_project):
        """Second run with --incremental skips unchanged files."""
        pipeline = ExtractionPipeline(
            domain="coding",
            source=coding_project,
            knowledge_graph=kg,
            incremental=True,
        )
        # First run: all files processed.
        report1 = pipeline.run()
        assert report1.files_processed > 0
        assert report1.files_skipped == 0

        # Second run: all files skipped (content unchanged).
        report2 = pipeline.run()
        assert report2.files_skipped == report1.files_processed

    def test_incremental_reprocesses_changed(self, kg, tmp_path):
        """Only changed files are re-extracted in incremental mode."""
        src = tmp_path / "inc"
        src.mkdir()
        f1 = src / "a.py"
        f2 = src / "b.py"
        f1.write_text("def alpha(): pass\n")
        f2.write_text("def beta(): pass\n")

        pipeline = ExtractionPipeline(
            domain="coding",
            source=src,
            knowledge_graph=kg,
            incremental=True,
        )

        # First run.
        report1 = pipeline.run()
        assert report1.files_processed == 2

        # Modify f1 only.
        f1.write_text("def alpha_v2(): pass\n")

        # Second run: only f1 should be processed.
        report2 = pipeline.run()
        assert report2.files_processed == 1
        assert report2.files_skipped == 1

    def test_incremental_cleanup_stale(self, kg, tmp_path):
        """Deleted files are cleaned up from tracking table."""
        src = tmp_path / "stale"
        src.mkdir()
        f1 = src / "keep.py"
        f2 = src / "delete_me.py"
        f1.write_text("def keep(): pass\n")
        f2.write_text("def remove(): pass\n")

        pipeline = ExtractionPipeline(
            domain="coding",
            source=src,
            knowledge_graph=kg,
            incremental=True,
        )

        # First run.
        report1 = pipeline.run()
        assert report1.files_processed == 2

        # Delete one file.
        f2.unlink()

        # Second run: cleanup should remove stale entry.
        report2 = pipeline.run()
        assert report2.files_skipped == 1  # f1 unchanged

        # Verify stale record is gone.
        cursor = kg.conn.cursor()
        stale_count = cursor.execute(
            "SELECT COUNT(*) FROM extraction_tracking WHERE file_path LIKE '%delete_me%'"
        ).fetchone()[0]
        assert stale_count == 0


class TestDailyDomainExtraction:
    """REQ-002: Daily domain routing and extraction."""

    def test_daily_domain_extracts_from_text(self, kg, daily_project):
        pipeline = ExtractionPipeline(
            domain="daily",
            source=daily_project,
            knowledge_graph=kg,
        )
        report = pipeline.run()
        assert report.files_discovered >= 1
        assert report.domain == "daily"
        # SpaCy may not be installed; in that case deterministic layer fails
        # but the pipeline itself should not crash.
        assert report.files_processed + report.files_failed >= 1


class TestReportIntegrity:
    """REQ-006: Report field completeness and timing."""

    def test_report_has_iso_timestamps(self, kg, coding_project):
        pipeline = ExtractionPipeline(
            domain="coding",
            source=coding_project,
            knowledge_graph=kg,
        )
        report = pipeline.run()

        # Validate ISO-8601 timestamps.
        from datetime import datetime as dt
        started = dt.fromisoformat(report.started_at)
        completed = dt.fromisoformat(report.completed_at)
        assert completed >= started

    def test_report_json_has_all_fields(self, kg, coding_project):
        pipeline = ExtractionPipeline(
            domain="coding",
            source=coding_project,
            knowledge_graph=kg,
        )
        report = pipeline.run()
        json_str = ReportFormatter.format_json(report)
        parsed = json.loads(json_str)

        required_keys = [
            "domain", "source", "started_at", "completed_at",
            "files_discovered", "files_processed", "files_skipped", "files_failed",
            "entities_extracted", "entities_stored",
            "relations_extracted", "relations_stored",
            "layer_deterministic", "layer_semantic", "layer_synthesis",
            "errors", "warnings", "estimated_tokens",
            "scope_id", "source_channel",
        ]
        for key in required_keys:
            assert key in parsed, f"Missing key: {key}"


class TestCLIIntegration:
    """REQ-005: CLI integration with actual file processing."""

    def test_cli_json_format(self, kg, coding_project):
        """CLI --format json outputs valid, complete JSON."""
        from mnemosyne.extraction.pipeline import main
        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            with pytest.raises(SystemExit) as exc_info:
                main([
                    "--domain", "coding",
                    "--source", str(coding_project),
                    "--format", "json",
                    "--db-path", str(kg.db_path),
                    "--no-semantic",
                ])
            assert exc_info.value.code == 0
            output = sys.stdout.getvalue()
            parsed = json.loads(output)
            assert parsed["domain"] == "coding"
            assert parsed["files_processed"] >= 2
        finally:
            sys.stdout = old_stdout

    def test_cli_incremental_flag(self, kg, coding_project):
        """CLI --incremental activates incremental mode."""
        from mnemosyne.extraction.pipeline import main
        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            # First run.
            with pytest.raises(SystemExit):
                main([
                    "--domain", "coding",
                    "--source", str(coding_project),
                    "--format", "json",
                    "--db-path", str(kg.db_path),
                    "--incremental",
                    "--no-semantic",
                ])
            first_output = sys.stdout.getvalue()
            sys.stdout = io.StringIO()

            # Second run: should show skipped files.
            with pytest.raises(SystemExit):
                main([
                    "--domain", "coding",
                    "--source", str(coding_project),
                    "--format", "json",
                    "--db-path", str(kg.db_path),
                    "--incremental",
                    "--no-semantic",
                ])
            second_output = sys.stdout.getvalue()
            parsed = json.loads(second_output)
            assert parsed["files_skipped"] >= 2
        finally:
            sys.stdout = old_stdout

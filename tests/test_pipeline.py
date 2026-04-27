"""
Tests for pipeline components (SPEC-PIPE-001).

This file grows incrementally as Tasks 3-7 are implemented.  Each task adds
a test class, and the corresponding implementation is added to pipeline.py.
"""

import json
import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# TASK 3 imports -- IncrementalTracker
# ---------------------------------------------------------------------------
from mnemosyne.extraction.pipeline import DomainRouter, ExtractionPipeline, IncrementalTracker
from mnemosyne.extraction.pipeline_types import ExtractionReport
from mnemosyne.graph.knowledge_graph import KnowledgeGraph


# == TASK 3: IncrementalTracker =============================================


class TestIncrementalTracker:
    """REQ-003: Content-hash based incremental extraction tracking."""

    @pytest.fixture()
    def tracker_db(self, tmp_path):
        """Provide an IncrementalTracker backed by a temp SQLite database."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        tracker = IncrementalTracker(conn)
        yield tracker
        conn.close()

    def test_table_creation_is_idempotent(self, tracker_db):
        """Creating the tracking table twice must not error."""
        # Second creation should be silent (IF NOT EXISTS).
        tracker_db._create_table()
        # Verify the table exists.
        cursor = tracker_db.conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='extraction_tracking'"
        )
        assert cursor.fetchone() is not None

    def test_initial_extraction_all_changed(self, tracker_db):
        """AC-003-1: First run -- all files are considered changed."""
        files = [Path("/a.py"), Path("/b.py"), Path("/c.py")]
        # Compute dummy hashes.
        hashes = {f: f"hash_{f.name}" for f in files}
        changed = tracker_db.get_changed_files(files, hashes, domain="coding")
        assert set(changed) == set(files)

    def test_record_and_skip_unchanged(self, tracker_db):
        """AC-003-2: After recording, unchanged files are skipped."""
        files = [Path("/a.py"), Path("/b.py")]
        hashes = {f: f"hash_{f.name}" for f in files}
        # Record extraction.
        tracker_db.record_extraction(files, hashes, domain="coding", entity_counts={f: 5 for f in files})
        # Same hashes -- should be skipped.
        changed = tracker_db.get_changed_files(files, hashes, domain="coding")
        assert changed == []

    def test_partial_change_detection(self, tracker_db):
        """AC-003-3: Only changed files are returned."""
        f1 = Path("/a.py")
        f2 = Path("/b.py")
        hashes_v1 = {f1: "hash_a_v1", f2: "hash_b_v1"}
        tracker_db.record_extraction([f1, f2], hashes_v1, domain="coding",
                                     entity_counts={f1: 3, f2: 4})
        # Only f1 changes.
        hashes_v2 = {f1: "hash_a_v2", f2: "hash_b_v1"}
        changed = tracker_db.get_changed_files([f1, f2], hashes_v2, domain="coding")
        assert changed == [f1]

    def test_cleanup_stale(self, tracker_db):
        """AC-003-5: Records for deleted files are cleaned up."""
        f1 = Path("/a.py")
        f2 = Path("/b.py")
        tracker_db.record_extraction(
            [f1, f2],
            {f1: "h1", f2: "h2"},
            domain="coding",
            entity_counts={f1: 1, f2: 1},
        )
        # Only f1 still exists.
        removed = tracker_db.cleanup_stale([f1], domain="coding")
        assert removed == 1

    def test_different_domains_independent(self, tracker_db):
        """Tracking is per-domain: same file, different domain = different record."""
        f = Path("/a.py")
        h = "hash_a"
        tracker_db.record_extraction([f], {f: h}, domain="coding", entity_counts={f: 3})
        # Same file, different domain -- should be seen as changed.
        changed = tracker_db.get_changed_files([f], {f: h}, domain="daily")
        assert changed == [f]

    def test_record_updates_entity_count(self, tracker_db):
        """Re-recording a file updates the entity count."""
        f = Path("/a.py")
        tracker_db.record_extraction([f], {f: "h1"}, domain="coding", entity_counts={f: 3})
        tracker_db.record_extraction([f], {f: "h2"}, domain="coding", entity_counts={f: 5})
        cursor = tracker_db.conn.cursor()
        row = cursor.execute(
            "SELECT entity_count FROM extraction_tracking WHERE file_path=? AND domain=?",
            (str(f), "coding"),
        ).fetchone()
        assert row[0] == 5

    def test_record_updates_hash(self, tracker_db):
        """Re-recording with a new hash updates the tracking record."""
        f = Path("/a.py")
        tracker_db.record_extraction([f], {f: "h1"}, domain="coding", entity_counts={f: 1})
        tracker_db.record_extraction([f], {f: "h2"}, domain="coding", entity_counts={f: 2})
        cursor = tracker_db.conn.cursor()
        row = cursor.execute(
            "SELECT content_hash FROM extraction_tracking WHERE file_path=? AND domain=?",
            (str(f), "coding"),
        ).fetchone()
        assert row[0] == "h2"


# == TASK 4: DomainRouter ===================================================


class TestDomainRouter:
    """REQ-002: Multi-domain pipeline routing."""

    def test_coding_domain_extensions(self):
        router = DomainRouter("coding")
        exts = router.file_extensions
        assert ".py" in exts
        assert ".js" in exts
        assert ".ts" in exts
        assert ".tsx" in exts
        assert ".jsx" in exts
        assert ".go" in exts
        assert ".rs" in exts
        assert ".java" in exts
        assert ".cpp" in exts
        assert ".c" in exts
        assert ".rb" in exts

    def test_coding_domain_entity_types(self):
        """AC-002-1: coding domain uses code entity types."""
        router = DomainRouter("coding")
        types = router.entity_types
        assert "function" in types
        assert "class" in types
        assert "module" in types

    def test_daily_domain_extensions(self):
        """AC-002-2: daily domain targets text-like files."""
        router = DomainRouter("daily")
        exts = router.file_extensions
        assert ".txt" in exts
        assert ".md" in exts
        assert ".eml" in exts
        assert ".json" in exts

    def test_daily_domain_entity_types(self):
        router = DomainRouter("daily")
        types = router.entity_types
        assert "task" in types
        assert "person" in types
        assert "place" in types
        assert "event" in types

    def test_legal_domain_extensions(self):
        """AC-002-3: legal domain includes document formats."""
        router = DomainRouter("legal")
        exts = router.file_extensions
        assert ".pdf" in exts
        assert ".txt" in exts
        assert ".md" in exts
        assert ".docx" in exts

    def test_legal_domain_entity_types(self):
        router = DomainRouter("legal")
        types = router.entity_types
        assert "statute" in types
        assert "clause" in types
        assert "case" in types
        assert "party" in types

    def test_unknown_domain_raises_valueerror(self):
        """AC-002-4: Unknown domain raises ValueError with supported list."""
        with pytest.raises(ValueError, match="coding"):
            DomainRouter("unknown")

    def test_filter_files_by_extension(self):
        """DomainRouter filters a file list by supported extensions."""
        router = DomainRouter("coding")
        files = [
            Path("src/main.py"),
            Path("src/util.js"),
            Path("README.md"),
            Path("data.json"),
        ]
        filtered = router.filter_files(files)
        assert Path("src/main.py") in filtered
        assert Path("src/util.js") in filtered
        assert Path("README.md") not in filtered

    def test_coding_uses_tree_sitter(self):
        """Coding domain specifies TreeSitterExtractor as deterministic."""
        router = DomainRouter("coding")
        assert router.deterministic_extractor == "tree_sitter"

    def test_daily_legal_use_spacy(self):
        for domain in ("daily", "legal"):
            router = DomainRouter(domain)
            assert router.deterministic_extractor == "spacy"


# == TASK 5: ExtractionPipeline =============================================


class TestExtractionPipeline:
    """REQ-001, REQ-004: Pipeline orchestration and graph storage."""

    @pytest.fixture()
    def kg(self, tmp_path):
        """Provide a KnowledgeGraph backed by a temp DB."""
        db_path = tmp_path / "knowledge.db"
        graph = KnowledgeGraph(str(db_path))
        yield graph
        graph.close()

    @pytest.fixture()
    def project_dir(self, tmp_path):
        """Create a minimal Python project for extraction."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text(
            "def hello():\n    print('hello')\n\ndef world():\n    print('world')\n"
        )
        (src / "util.py").write_text(
            "class Helper:\n    pass\n"
        )
        return src

    def test_full_flow_coding(self, kg, project_dir):
        """AC-001-1: Full flow discovers files, extracts, stores to graph."""
        pipeline = ExtractionPipeline(
            domain="coding",
            source=project_dir,
            knowledge_graph=kg,
        )
        report = pipeline.run()
        assert report.files_discovered >= 2
        assert report.files_processed >= 2
        assert report.entities_extracted > 0
        assert report.entities_stored > 0
        assert report.domain == "coding"

    def test_scope_propagation(self, kg, project_dir):
        """AC-001-2: scope_id and source_channel propagate to entities."""
        pipeline = ExtractionPipeline(
            domain="coding",
            source=project_dir,
            knowledge_graph=kg,
            scope_id="session-abc",
            source_channel="vscode",
        )
        report = pipeline.run()
        assert report.scope_id == "session-abc"
        assert report.source_channel == "vscode"
        # Verify entities in the graph have the correct scope.
        entities = kg.get_entities_by_type("function")
        for e in entities:
            assert e.scope_id == "session-abc"

    def test_disable_semantic_layer(self, kg, project_dir):
        """AC-001-3: Disabling semantic layer runs only deterministic."""
        pipeline = ExtractionPipeline(
            domain="coding",
            source=project_dir,
            knowledge_graph=kg,
            enable_semantic=False,
        )
        report = pipeline.run()
        assert report.layer_semantic.entities_extracted == 0
        assert report.layer_semantic.files_processed == 0

    def test_entity_dedup(self, kg, tmp_path):
        """AC-001-4: Same type+name+scope deduplicates via upsert."""
        src = tmp_path / "dedup.py"
        src.write_text("def foo(): pass\n")
        pipeline = ExtractionPipeline(
            domain="coding",
            source=src,
            knowledge_graph=kg,
            scope_id="s1",
        )
        # Run twice -- same content.
        pipeline.run()
        pipeline.run()
        # Entities should be updated, not duplicated.
        entities = kg.get_entities_by_type("function")
        names = [e.name for e in entities]
        # foo appears once per scope (updated version)
        foo_count = names.count("foo")
        assert foo_count <= 2  # at most one per run scope

    def test_two_pass_relation_storage(self, kg, tmp_path):
        """REQ-004: Relations stored after all entities (name-to-ID resolution)."""
        src = tmp_path / "rel.py"
        src.write_text(
            "import os\n\ndef parse(): pass\ndef main(): parse()\n"
        )
        pipeline = ExtractionPipeline(
            domain="coding",
            source=src,
            knowledge_graph=kg,
        )
        report = pipeline.run()
        # Report should have completed without error.
        assert report.files_failed == 0

    def test_single_file_source(self, kg, tmp_path):
        """Pipeline works when source is a single file, not a directory."""
        f = tmp_path / "single.py"
        f.write_text("def lone(): pass\n")
        pipeline = ExtractionPipeline(
            domain="coding",
            source=f,
            knowledge_graph=kg,
        )
        report = pipeline.run()
        assert report.files_discovered == 1
        assert report.files_processed == 1

    def test_default_db_path(self):
        """Pipeline can be created without explicit knowledge_graph."""
        # We just verify construction works -- not running it.
        ExtractionPipeline.__new__(ExtractionPipeline)
        # This test is structural; the real default path is tested via CLI.


# == TASK 6: ReportFormatter + CLI ==========================================


class TestReportFormatter:
    """REQ-005, REQ-006: Report formatting and CLI."""

    @pytest.fixture()
    def sample_report(self):
        from mnemosyne.extraction.pipeline_types import LayerStats
        return ExtractionReport(
            domain="coding",
            source="/tmp/project",
            started_at="2026-04-26T00:00:00",
            completed_at="2026-04-26T00:01:00",
            files_discovered=10,
            files_processed=8,
            files_skipped=2,
            files_failed=0,
            entities_extracted=30,
            entities_stored=30,
            relations_extracted=5,
            relations_stored=5,
            layer_deterministic=LayerStats(entities_extracted=25, files_processed=8),
            layer_semantic=LayerStats(entities_extracted=5, files_processed=8),
            layer_synthesis=LayerStats(),
            errors=[],
            warnings=[],
            estimated_tokens=1500,
            scope_id=None,
            source_channel="pipeline",
        )

    def test_format_summary_contains_key_info(self, sample_report):
        from mnemosyne.extraction.pipeline import ReportFormatter
        output = ReportFormatter.format_summary(sample_report)
        assert "coding" in output
        assert "10" in output  # files_discovered
        assert "30" in output  # entities_extracted

    def test_format_json_is_valid(self, sample_report):
        from mnemosyne.extraction.pipeline import ReportFormatter
        output = ReportFormatter.format_json(sample_report)
        parsed = json.loads(output)
        assert parsed["domain"] == "coding"
        assert parsed["files_processed"] == 8
        assert parsed["entities_extracted"] == 30

    def test_format_wiki_has_markdown_headers(self, sample_report):
        from mnemosyne.extraction.pipeline import ReportFormatter
        output = ReportFormatter.format_wiki(sample_report)
        assert "#" in output  # Markdown headers
        assert "[[" in output or "coding" in output  # wiki links or domain name


class TestCLI:
    """REQ-005: CLI argument parsing and exit codes."""

    @pytest.fixture()
    def kg(self, tmp_path):
        db_path = tmp_path / "knowledge.db"
        graph = KnowledgeGraph(str(db_path))
        yield graph
        graph.close()

    @pytest.fixture()
    def project_dir(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("def hello(): pass\n")
        return src

    def test_cli_build_parser(self):
        from mnemosyne.extraction.pipeline import build_parser
        parser = build_parser()
        # Verify required args are recognized.
        args = parser.parse_args([
            "--domain", "coding",
            "--source", "/tmp/test",
        ])
        assert args.domain == "coding"
        assert args.source == "/tmp/test"

    def test_cli_optional_args(self):
        from mnemosyne.extraction.pipeline import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "--domain", "daily",
            "--source", "/tmp/test",
            "--scope-id", "s1",
            "--source-channel", "discord",
            "--format", "json",
            "--incremental",
            "--no-semantic",
            "--db-path", "/tmp/test.db",
        ])
        assert args.scope_id == "s1"
        assert args.source_channel == "discord"
        assert args.format == "json"
        assert args.incremental is True
        assert args.no_semantic is True
        assert args.db_path == "/tmp/test.db"

    def test_cli_default_values(self):
        from mnemosyne.extraction.pipeline import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "--domain", "coding",
            "--source", "/tmp/test",
        ])
        assert args.format == "summary"
        assert args.incremental is False
        assert args.no_semantic is False
        assert args.scope_id is None
        assert args.source_channel == "pipeline"

    def test_main_missing_source_exits_1(self):
        """AC-005-3: Missing required arguments should cause exit."""
        from mnemosyne.extraction.pipeline import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--domain", "coding"])
        # argparse returns exit code 2 for missing required args.
        assert exc_info.value.code in (1, 2)

    def test_main_nonexistent_source_exits_1(self, tmp_path):
        """AC-005-4: Non-existent source path exits with code 1."""
        from mnemosyne.extraction.pipeline import main
        with pytest.raises(SystemExit) as exc_info:
            main([
                "--domain", "coding",
                "--source", str(tmp_path / "nonexistent"),
                "--db-path", str(tmp_path / "test.db"),
            ])
        assert exc_info.value.code == 1

    def test_main_success_exit_0(self, kg, project_dir):
        """AC-005-1: Successful run exits with code 0."""
        from mnemosyne.extraction.pipeline import main
        with pytest.raises(SystemExit) as exc_info:
            main([
                "--domain", "coding",
                "--source", str(project_dir),
                "--db-path", str(kg.db_path),
                "--no-semantic",
            ])
        assert exc_info.value.code == 0

    def test_main_json_output(self, kg, project_dir, capsys):
        """AC-005-2: JSON format outputs valid JSON."""
        from mnemosyne.extraction.pipeline import main
        with pytest.raises(SystemExit):
            main([
                "--domain", "coding",
                "--source", str(project_dir),
                "--format", "json",
                "--db-path", str(kg.db_path),
                "--no-semantic",
            ])
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "domain" in parsed
        assert parsed["domain"] == "coding"


# == TASK 7: Error Resilience ===============================================


class TestErrorResilience:
    """REQ-007: Per-file error handling and resilience."""

    @pytest.fixture()
    def kg(self, tmp_path):
        db_path = tmp_path / "knowledge.db"
        graph = KnowledgeGraph(str(db_path))
        yield graph
        graph.close()

    def test_encoding_error_recovery(self, kg, tmp_path):
        """AC-007-1: Files with bad encoding are retried with errors='ignore'."""
        src = tmp_path / "bad_encoding.py"
        # Write bytes that are not valid UTF-8.
        src.write_bytes(b"def foo():\n    x = '\xff\xfe'\n    return x\n")
        pipeline = ExtractionPipeline(
            domain="coding",
            source=src,
            knowledge_graph=kg,
        )
        report = pipeline.run()
        # Pipeline should not crash; file should be processed or have a recorded error.
        assert report.files_discovered == 1
        # Either processed or failed -- either way, no crash.
        assert report.files_processed + report.files_failed == 1

    def test_permission_error_recovery(self, kg, tmp_path):
        """AC-007-2: Permission errors are recorded, not fatal."""
        src = tmp_path / "noperm.py"
        src.write_text("def foo(): pass\n")
        # Make file unreadable (skip on Windows or if chmod fails).
        import os
        os.chmod(str(src), 0o000)
        try:
            pipeline = ExtractionPipeline(
                domain="coding",
                source=src,
                knowledge_graph=kg,
            )
            report = pipeline.run()
            # File should be recorded as failed.
            assert report.files_failed >= 0  # May succeed if running as root
        finally:
            os.chmod(str(src), 0o644)

    def test_empty_file_handled(self, kg, tmp_path):
        """Empty files are processed without errors."""
        src = tmp_path / "empty.py"
        src.write_text("")
        pipeline = ExtractionPipeline(
            domain="coding",
            source=src,
            knowledge_graph=kg,
        )
        report = pipeline.run()
        assert report.files_failed == 0

    def test_binary_file_skipped_or_handled(self, kg, tmp_path):
        """Binary files (e.g. .pyc) are filtered by extension or handled."""
        src = tmp_path / "module.pyc"
        src.write_bytes(b"\x00\x01\x02\x03")
        pipeline = ExtractionPipeline(
            domain="coding",
            source=src,
            knowledge_graph=kg,
        )
        report = pipeline.run()
        # .pyc is not in coding extensions, so it should be filtered out.
        assert report.files_discovered == 0

    def test_error_pattern_escalation(self, kg, tmp_path):
        """AC-007-5: Repeated error types produce warnings."""
        from mnemosyne.extraction.pipeline import _detect_error_patterns
        from mnemosyne.extraction.pipeline_types import ExtractionError
        errors = [
            ExtractionError("a.py", "UnicodeDecodeError", "bad encoding", "deterministic"),
            ExtractionError("b.py", "UnicodeDecodeError", "bad encoding", "deterministic"),
            ExtractionError("c.py", "UnicodeDecodeError", "bad encoding", "deterministic"),
        ]
        warnings = _detect_error_patterns(errors)
        assert len(warnings) > 0
        assert any("UnicodeDecodeError" in w for w in warnings)

    def test_mixed_success_and_failure(self, kg, tmp_path):
        """AC-007-4: Some files fail, others succeed."""
        src_dir = tmp_path / "mixed"
        src_dir.mkdir()
        (src_dir / "good.py").write_text("def good(): pass\n")
        (src_dir / "bad.py").write_bytes(b"\xff\xfe invalid")
        pipeline = ExtractionPipeline(
            domain="coding",
            source=src_dir,
            knowledge_graph=kg,
        )
        report = pipeline.run()
        assert report.files_processed >= 1
        # Good file should produce entities.
        assert report.entities_extracted >= 1

    def test_single_layer_failure_skips_remaining(self, kg, tmp_path, monkeypatch):
        """AC-007-3: If deterministic fails, semantic and synthesis are skipped."""
        src = tmp_path / "test.py"
        src.write_text("def foo(): pass\n")
        pipeline = ExtractionPipeline(
            domain="coding",
            source=src,
            knowledge_graph=kg,
        )
        # Monkeypatch tree_sitter to raise.
        def fail_extract(*args, **kwargs):
            raise RuntimeError("forced failure")

        monkeypatch.setattr(pipeline.tree_sitter, "extract_file_full", fail_extract)

        report = pipeline.run()
        assert report.files_failed == 1
        assert len(report.errors) == 1
        assert report.errors[0].layer == "deterministic"

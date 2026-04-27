"""
Tests for pipeline_types data models (SPEC-PIPE-001 REQ-003, REQ-006).

Covers: ExtractionResult, ExtractionError, LayerStats, ExtractionReport,
content_hash utility.
"""




# ---------------------------------------------------------------------------
# RED: All imports target pipeline_types which does not exist yet.
# ---------------------------------------------------------------------------

from mnemosyne.extraction.pipeline_types import (
    ExtractionError,
    ExtractionReport,
    ExtractionResult,
    LayerStats,
    content_hash,
)


# -- ExtractionError --------------------------------------------------------

class TestExtractionError:
    """REQ-007: Per-file extraction error record."""

    def test_creation_with_required_fields(self):
        err = ExtractionError(
            file_path="/app/main.py",
            error_type="UnicodeDecodeError",
            error_message="invalid utf-8 byte sequence",
            layer="deterministic",
        )
        assert err.file_path == "/app/main.py"
        assert err.error_type == "UnicodeDecodeError"
        assert err.error_message == "invalid utf-8 byte sequence"
        assert err.layer == "deterministic"
        assert err.traceback is None

    def test_creation_with_traceback(self):
        err = ExtractionError(
            file_path="f.py",
            error_type="PermissionError",
            error_message="denied",
            layer="semantic",
            traceback="Traceback...",
        )
        assert err.traceback == "Traceback..."


# -- LayerStats --------------------------------------------------------------

class TestLayerStats:
    """REQ-006: Per-layer statistics."""

    def test_default_values(self):
        stats = LayerStats()
        assert stats.entities_extracted == 0
        assert stats.relations_extracted == 0
        assert stats.files_processed == 0
        assert stats.files_failed == 0
        assert stats.estimated_tokens == 0

    def test_custom_values(self):
        stats = LayerStats(
            entities_extracted=10,
            relations_extracted=3,
            files_processed=5,
            files_failed=1,
            estimated_tokens=500,
        )
        assert stats.entities_extracted == 10
        assert stats.relations_extracted == 3


# -- ExtractionResult --------------------------------------------------------

class TestExtractionResult:
    """REQ-001: Single file/text extraction result."""

    def test_creation(self):
        result = ExtractionResult(
            source="/app/main.py",
            entities=[{"type": "function", "name": "foo"}],
            relations=[],
            errors=[],
            layers_used=["deterministic"],
            estimated_tokens=100,
        )
        assert result.source == "/app/main.py"
        assert len(result.entities) == 1
        assert result.layers_used == ["deterministic"]
        assert result.estimated_tokens == 100

    def test_default_collections(self):
        result = ExtractionResult(source="test.txt")
        assert result.entities == []
        assert result.relations == []
        assert result.errors == []
        assert result.layers_used == []
        assert result.estimated_tokens == 0


# -- ExtractionReport --------------------------------------------------------

class TestExtractionReport:
    """REQ-006: Full pipeline extraction report."""

    def _make_report(self, **overrides):
        defaults = dict(
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
            layer_deterministic=LayerStats(entities_extracted=25),
            layer_semantic=LayerStats(entities_extracted=5),
            layer_synthesis=LayerStats(),
            errors=[],
            warnings=[],
            estimated_tokens=1500,
            scope_id=None,
            source_channel="pipeline",
        )
        defaults.update(overrides)
        return ExtractionReport(**defaults)

    def test_report_has_all_fields(self):
        report = self._make_report()
        assert report.domain == "coding"
        assert report.source == "/tmp/project"
        assert report.files_discovered == 10
        assert report.files_processed == 8
        assert report.files_skipped == 2
        assert report.files_failed == 0
        assert report.entities_extracted == 30
        assert report.entities_stored == 30
        assert report.relations_extracted == 5
        assert report.relations_stored == 5
        assert isinstance(report.layer_deterministic, LayerStats)
        assert isinstance(report.layer_semantic, LayerStats)
        assert isinstance(report.layer_synthesis, LayerStats)
        assert report.errors == []
        assert report.warnings == []
        assert report.estimated_tokens == 1500
        assert report.scope_id is None
        assert report.source_channel == "pipeline"

    def test_report_with_errors(self):
        err = ExtractionError(
            file_path="bad.py",
            error_type="PermissionError",
            error_message="denied",
            layer="deterministic",
        )
        report = self._make_report(errors=[err], files_failed=1, files_processed=7)
        assert len(report.errors) == 1
        assert report.files_failed == 1


# -- content_hash utility ----------------------------------------------------

class TestContentHash:
    """REQ-003: SHA-256 content hash for incremental tracking."""

    def test_deterministic(self):
        data = b"hello world"
        h1 = content_hash(data)
        h2 = content_hash(data)
        assert h1 == h2

    def test_length_is_16(self):
        """First 16 hex chars of SHA-256."""
        h = content_hash(b"test")
        assert len(h) == 16

    def test_different_inputs_different_hashes(self):
        h1 = content_hash(b"aaa")
        h2 = content_hash(b"bbb")
        assert h1 != h2

    def test_empty_input(self):
        h = content_hash(b"")
        assert len(h) == 16

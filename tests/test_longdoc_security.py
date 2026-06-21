"""Tests for SPEC-LONGDOC-001 REQ-LD-001 / REQ-LD-008 (partial):

- AC-1 (detector): ``detect_longdoc`` returns True past token / page thresholds.
- AC-8 (security, partial): ``validate_longdoc_path`` rejects ``..`` segments
  and absolute paths outside the raw root. Full security review (memory
  bounds, streaming, >1000-page rejection) is deferred to the mandatory
  REVIEW phase per SPEC §10.
- PDF splitter soft-dependency: ``pymupdf`` absent raises ImportError, which
  the indexer surface lets the caller translate into ExtractionError skip.
"""

import pytest

from mnemosyne.extraction.longdoc.detector import (
    LONGDOC_DEFAULT_PAGE_THRESHOLD,
    LONGDOC_DEFAULT_TOKEN_THRESHOLD,
    detect_longdoc,
    longdoc_page_threshold,
    longdoc_token_threshold,
)
from mnemosyne.extraction.longdoc.security import (
    LongDocPathError,
    validate_longdoc_path,
)
from mnemosyne.extraction.longdoc.tree_indexer import split_pdf_pages


# -- AC-1: detector thresholds ---------------------------------------------


class TestLongDocDetector:
    def test_below_thresholds_is_not_long(self):
        assert detect_longdoc(estimated_tokens=100, page_count=1) is False

    def test_token_threshold_trips(self):
        assert detect_longdoc(
            estimated_tokens=LONGDOC_DEFAULT_TOKEN_THRESHOLD + 1, page_count=0
        ) is True

    def test_page_threshold_trips(self):
        assert detect_longdoc(
            estimated_tokens=100, page_count=LONGDOC_DEFAULT_PAGE_THRESHOLD + 1
        ) is True

    def test_custom_thresholds_via_env(self, monkeypatch):
        monkeypatch.setenv("MNEMOSYNE_LONGDOC_THRESHOLD", "50")
        monkeypatch.setenv("MNEMOSYNE_LONGDOC_PAGE_THRESHOLD", "2")
        # Re-read thresholds (env is consulted at call time).
        assert longdoc_token_threshold() == 50
        assert longdoc_page_threshold() == 2
        assert detect_longdoc(estimated_tokens=51, page_count=0) is True
        assert detect_longdoc(estimated_tokens=10, page_count=3) is True

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("MNEMOSYNE_LONGDOC_THRESHOLD", "not-a-number")
        assert longdoc_token_threshold() == LONGDOC_DEFAULT_TOKEN_THRESHOLD


# -- AC-8 partial: path traversal guard ------------------------------------


class TestPathTraversalGuard:
    def test_rejects_dotdot_segment(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        with pytest.raises(LongDocPathError, match="\\.\\."):
            validate_longdoc_path("safe/../../etc/passwd", raw)

    def test_rejects_absolute_path_outside_raw_root(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        outside = tmp_path / "outside" / "secret.md"
        with pytest.raises(LongDocPathError, match="outside"):
            validate_longdoc_path(outside, raw)

    def test_accepts_relative_path_under_raw_root(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        resolved = validate_longdoc_path("doc.md", raw)
        assert resolved == raw / "doc.md"

    def test_accepts_absolute_path_inside_raw_root(self, tmp_path):
        raw = tmp_path / "raw"
        (raw / "sub").mkdir(parents=True)
        inside = raw / "sub" / "doc.md"
        inside.touch()
        resolved = validate_longdoc_path(inside, raw)
        assert resolved == inside.resolve()


# -- AC-8 partial: PDF soft-dependency -------------------------------------


class TestPDFSoftDependency:
    def test_split_pdf_pages_raises_when_pymupdf_absent(self, tmp_path):
        """When pymupdf (fitz) is not importable, the splitter raises
        ImportError so the pipeline can degrade gracefully."""
        try:
            import fitz  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            with pytest.raises(ImportError, match="pymupdf"):
                split_pdf_pages(tmp_path / "fake.pdf")
        else:
            pytest.skip("pymupdf is installed; cannot test absence path")

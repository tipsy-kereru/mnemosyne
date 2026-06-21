"""Tests for SPEC-LONGDOC-001 REQ-LD-001 / REQ-LD-008 (partial):

- AC-1 (detector): ``detect_longdoc`` returns True past token / page thresholds.
- AC-8 (security, partial): ``validate_longdoc_path`` rejects ``..`` segments
  and absolute paths outside the raw root. Full security review (memory
  bounds, streaming, >1000-page rejection) is deferred to the mandatory
  REVIEW phase per SPEC §10.
- PDF splitter soft-dependency: ``pymupdf`` absent raises ImportError, which
  the indexer surface lets the caller translate into ExtractionError skip.
- REVIEW-phase hardening: validator encoding/backslash bypass, memory-bound
  caps (page/file/node), required raw_root, redaction.
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
    redact,
    validate_longdoc_path,
)
from mnemosyne.extraction.longdoc.tree_indexer import (
    LongDocIndexer,
    split_pdf_pages,
)


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


# -- REVIEW-phase hardening: validator encoding/backslash bypass -----------


class TestValidatorBypassHardening:
    def test_rejects_percent_encoded_dotdot(self, tmp_path):
        """%2e%2e must not bypass the lexical '..' guard."""
        raw = tmp_path / "raw"
        raw.mkdir()
        with pytest.raises(LongDocPathError, match="\\.\\."):
            validate_longdoc_path("safe/%2e%2e/%2e%2e/etc/passwd", raw)

    def test_rejects_backslash_separator(self, tmp_path):
        """Windows-style backslash '..\\..\\' must not bypass the guard."""
        raw = tmp_path / "raw"
        raw.mkdir()
        with pytest.raises(LongDocPathError, match="\\.\\."):
            validate_longdoc_path("..\\..\\etc\\passwd", raw)

    def test_rejects_mixed_percent_and_backslash(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        with pytest.raises(LongDocPathError):
            validate_longdoc_path("safe%2f%2e%2e\\secret", raw)


# -- REVIEW-phase hardening: required raw_root ----------------------------


class TestRequiredRawRoot:
    def test_indexer_rejects_none_raw_root(self, tmp_path):
        """raw_root=None must raise ValueError — validator never skipped."""
        from mnemosyne.graph.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph(db_path=str(tmp_path / "rr.db"))
        try:
            with pytest.raises(ValueError, match="raw_root"):
                LongDocIndexer(conn=kg.conn, entity_types=["note"])
        finally:
            kg.close()


# -- REVIEW-phase hardening: memory bounds --------------------------------


@pytest.fixture
def _kg(tmp_path):
    from mnemosyne.graph.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph(db_path=str(tmp_path / "bounds.db"))
    yield kg
    kg.close()


@pytest.fixture
def _raw_root(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    return root


class TestMemoryBounds:
    def test_rejects_oversize_file(self, _kg, _raw_root):
        """File > MAX_LONGDOC_BYTES must be rejected before any read."""
        f = _raw_root / "huge.md"
        f.write_bytes(b"x" * 16)  # tiny file; we mock stat instead
        idx = LongDocIndexer(
            conn=_kg.conn, entity_types=["note"], domain="daily",
            raw_root=_raw_root,
        )
        # Patch the module constant down so the test is fast and deterministic.
        import mnemosyne.extraction.longdoc.tree_indexer as ti
        original = ti.MAX_LONGDOC_BYTES
        ti.MAX_LONGDOC_BYTES = 8
        try:
            with pytest.raises(LongDocPathError, match="exceeds"):
                idx.index_file(f, source_hash="big")
        finally:
            ti.MAX_LONGDOC_BYTES = original

    def test_rejects_too_many_nodes(self, _kg, _raw_root):
        """Tree with > MAX_LONGDOC_NODES must raise."""
        # Build a markdown doc that fans out into many nodes.
        # ~50 sections * MAX_FANOUT grouping -> well under 5000 nodes normally,
        # so we patch the cap down to a small number for a deterministic test.
        body = "\n".join(f"# S{i}\n\ncontent {i}" for i in range(40))
        idx = LongDocIndexer(
            conn=_kg.conn, entity_types=["note"], domain="daily",
            raw_root=_raw_root,
        )
        import mnemosyne.extraction.longdoc.tree_indexer as ti
        original = ti.MAX_LONGDOC_NODES
        ti.MAX_LONGDOC_NODES = 3
        try:
            with pytest.raises(LongDocPathError, match="node cap"):
                idx.index_text(body, source_hash="toomany", kind="markdown")
        finally:
            ti.MAX_LONGDOC_NODES = original

    def test_rejects_oversize_pdf(self, _kg, _raw_root):
        """PDF with > MAX_LONGDOC_PAGES must raise before sectioning."""
        # Patch fitz.open with a fake doc that reports a huge page count.
        import mnemosyne.extraction.longdoc.tree_indexer as ti

        class _FakeDoc:
            def __init__(self, n):
                self._n = n

            def __len__(self):
                return self._n

            def load_page(self, i):
                raise AssertionError("load_page must not be called past cap")

            def close(self):
                pass

        class _FakeFitz:
            @staticmethod
            def open(path):
                return _FakeDoc(ti.MAX_LONGDOC_PAGES + 5)

        f = _raw_root / "big.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        idx = LongDocIndexer(
            conn=_kg.conn, entity_types=["note"], domain="daily",
            raw_root=_raw_root,
        )
        import builtins
        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "fitz":
                return _FakeFitz
            return real_import(name, *args, **kwargs)

        builtins.__import__ = _fake_import
        try:
            with pytest.raises(LongDocPathError, match="page cap"):
                idx.index_file(f, source_hash="bigpdf")
        finally:
            builtins.__import__ = real_import


# -- REVIEW-phase hardening: redaction ------------------------------------


class TestRedaction:
    def test_redact_github_token(self):
        out = redact("token: ghp_" + "a" * 36)
        assert "ghp_" not in out
        assert "[REDACTED" in out

    def test_redact_aws_key(self):
        out = redact("creds AKIA" + "ABCDEFGHJKLMNPQR")
        assert "AKIA" not in out

    def test_redact_none_safe(self):
        assert redact(None) == ""
        assert redact("") == ""

    def test_redact_private_key_block(self):
        block = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA\n"
            "-----END RSA PRIVATE KEY-----"
        )
        out = redact(block)
        assert "[REDACTED:private-key]" in out
        assert "MIIEowIBAAKCAQEA" not in out

    def test_redaction_applied_to_excerpt_and_refs(self, _kg, _raw_root):
        """raw_excerpt and entity_refs persisted to tree_nodes must be
        redacted of recognisable credentials."""
        idx = LongDocIndexer(
            conn=_kg.conn, entity_types=["note"], domain="daily",
            raw_root=_raw_root,
        )
        secret = "Bearer ghp_" + "b" * 36
        tree_id = idx.index_text(
            f"# Section\n\napi key {secret}", source_hash="red1", kind="markdown"
        )
        rows = _kg.conn.execute(
            "SELECT raw_excerpt, entity_refs FROM tree_nodes WHERE tree_id=?",
            (tree_id,),
        ).fetchall()
        assert rows, "expected at least one tree node"
        for row in rows:
            excerpt = row["raw_excerpt"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
            refs = row["entity_refs"] if isinstance(row, dict) or hasattr(row, "keys") else row[1]
            assert "ghp_" not in str(excerpt), f"leak in excerpt: {excerpt}"
            assert "ghp_" not in str(refs), f"leak in refs: {refs}"

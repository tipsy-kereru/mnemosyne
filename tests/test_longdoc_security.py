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

import ast
import inspect
from pathlib import Path

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

            @property
            def page_count(self):
                return self._n

            def __iter__(self):
                # Must never be called: cap fires first.
                raise AssertionError("iteration must not happen past cap")

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


# -- ISSUE-0003 T7: streaming parse regression + adversarial fuzz ------------


class TestStreamingParse:
    def test_split_pdf_pages_has_no_whole_doc_buffer(self):
        """AC-3 (revised): the splitter must not construct a whole-doc buffer.
        We walk the AST so comments/docstrings/strings do not yield false
        positives. Forbidden: any ``.write(...)`` call and any
        ``get_text("dict")`` call. Required: lazy ``enumerate(doc)``."""
        src = inspect.getsource(split_pdf_pages)
        tree = ast.parse(src)

        write_calls: list[str] = []
        get_text_dict_calls: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr == "write":
                    write_calls.append(attr)
                if attr == "get_text":
                    # First positional arg is the mode; "dict" is forbidden.
                    if node.args and isinstance(node.args[0], ast.Constant):
                        if node.args[0].value == "dict":
                            get_text_dict_calls.append("dict")
        assert not write_calls, (
            f"split_pdf_pages must not call .write(): {write_calls}"
        )
        assert not get_text_dict_calls, (
            "split_pdf_pages must not call get_text('dict') on the whole doc"
        )

    def test_split_pdf_pages_uses_lazy_enumerate(self):
        """AC-3 (revised): pages are iterated via ``enumerate(doc)``, not
        ``range(len(doc))`` + ``load_page``."""
        src = inspect.getsource(split_pdf_pages)
        # Lazy iteration via enumerate(doc), NOT range(len(doc)).
        assert "enumerate(doc)" in src, (
            f"split_pdf_pages must iterate lazily via enumerate(doc):\n{src}"
        )
        assert "range(len(doc))" not in src, (
            f"split_pdf_pages must not use range(len(doc)):\n{src}"
        )
        assert "load_page(" not in src, (
            f"split_pdf_pages must not double-lookup via load_page:\n{src}"
        )

    def test_split_pdf_pages_uses_page_count_not_len(self):
        """The page cap must check ``doc.page_count`` (property) rather than
        ``len(doc)`` — keeps it a catalogue lookup, not a materialisation."""
        src = inspect.getsource(split_pdf_pages)
        assert "doc.page_count" in src
        assert "len(doc)" not in src


class TestPDFAdversarialFuzz:
    """AC-4 (revised): 3 fuzz cases — truncated header, zero-page doc,
    sparse-file byte-cap rejection."""

    @pytest.fixture
    def _fitz_available(self):
        try:
            import fitz  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            pytest.skip("pymupdf (fitz) not installed; PDF fuzz tests skipped")

    def _has_fitz(self) -> bool:
        try:
            import fitz  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return False
        return True

    def test_truncated_pdf_header_raises(self, _kg, _raw_root, _fitz_available):
        """A file with valid PDF magic but a truncated body must raise
        (pymupdf will error) rather than crash the process. The longdoc
        surface translates pymupdf's error into a failure that the caller
        can wrap in ExtractionError(layer='longdoc')."""
        from mnemosyne.extraction.longdoc.tree_indexer import LongDocIndexer

        truncated = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"  # magic + truncated
        f = _raw_root / "truncated.pdf"
        f.write_bytes(truncated)

        idx = LongDocIndexer(
            conn=_kg.conn, entity_types=["note"], domain="daily",
            raw_root=_raw_root,
        )
        # Either pymupdf raises a raw exception, or LongDocIndexer surfaces a
        # wrapper. Both are acceptable; what is NOT acceptable is silent
        # success with a non-empty tree. We assert it raises (some exception)
        # and does not OOM/crash.
        with pytest.raises(Exception):
            idx.index_file(f, source_hash="trunc")

        # No tree should have been persisted for this source_hash.
        rows = _kg.conn.execute(
            "SELECT tree_id FROM document_trees WHERE source_hash=?",
            ("trunc",),
        ).fetchall()
        assert rows == [], "truncated PDF must not persist a tree"

    def test_zero_page_doc_returns_empty(self, _kg, _raw_root, _fitz_available):
        """AC-4(b): a PDF that opens cleanly but has 0 pages must produce an
        empty section list. ``split_pdf_pages`` returns ``[]`` and the
        indexer returns ``None`` (no tree built) — no crash."""
        import fitz  # type: ignore[import-not-found]

        # Build a real 0-page PDF via pymupdf: open() then save with no pages.
        f = _raw_root / "empty.pdf"
        doc = fitz.open()  # type: ignore[attr-defined]
        doc.save(str(f))
        doc.close()

        from mnemosyne.extraction.longdoc.tree_indexer import (
            LongDocIndexer,
            split_pdf_pages,
        )

        sections = split_pdf_pages(f)
        assert sections == [], "zero-page PDF must yield empty section list"

        idx = LongDocIndexer(
            conn=_kg.conn, entity_types=["note"], domain="daily",
            raw_root=_raw_root,
        )
        tree_id = idx.index_file(f, source_hash="zero")
        assert tree_id is None, "zero-page PDF must not build a tree"

    def test_sparse_file_byte_cap_rejects_before_read(
        self, _kg, _raw_root, _fitz_available
    ):
        """AC-4(c): a sparse file whose stat size exceeds ``MAX_LONGDOC_BYTES``
        must be rejected by the pre-read size check — no real allocation, no
        decompression. Proves the DoS-bound first line of defense."""
        import os

        import mnemosyne.extraction.longdoc.tree_indexer as ti
        from mnemosyne.extraction.longdoc.tree_indexer import LongDocIndexer

        f = _raw_root / "sparse.pdf"
        # Create a sparse file just over the cap. stat reports the large size
        # but no disk blocks are allocated — safe to create in tests.
        oversize = ti.MAX_LONGDOC_BYTES + 1024
        with open(f, "wb") as fh:
            fh.seek(oversize - 1)
            fh.write(b"\x00")

        idx = LongDocIndexer(
            conn=_kg.conn, entity_types=["note"], domain="daily",
            raw_root=_raw_root,
        )
        with pytest.raises(LongDocPathError, match="exceeds"):
            idx.index_file(f, source_hash="sparse")

        # Sanity: the file really did stat as oversize.
        assert os.path.getsize(f) > ti.MAX_LONGDOC_BYTES


# -- ISSUE-0003 T6: cap verification under load --------------------------------


class TestCapsHoldUnderBenchLoad:
    """AC-1 / AC-4: the existing caps (pages / bytes / nodes) hold when the
    indexer is exercised with benchmark-shaped input."""

    def test_node_cap_holds_on_dense_markdown(self, _kg, _raw_root):
        """A markdown doc that would fan out into many nodes is capped."""
        # 200 sections — enough to exercise grouping without exceeding the
        # default 5000-node cap on a normal machine.
        body = "\n".join(f"# S{i}\n\ncontent {i}" for i in range(200))
        idx = LongDocIndexer(
            conn=_kg.conn, entity_types=["note"], domain="coding",
            raw_root=_raw_root,
        )
        # Patch the node cap DOWN so we exercise the rejection path without
        # needing to build a genuinely huge doc.
        import mnemosyne.extraction.longdoc.tree_indexer as ti
        original = ti.MAX_LONGDOC_NODES
        ti.MAX_LONGDOC_NODES = 5
        try:
            with pytest.raises(LongDocPathError, match="node cap"):
                idx.index_text(body, source_hash="dense", kind="markdown")
        finally:
            ti.MAX_LONGDOC_NODES = original

    def test_byte_cap_constant_is_50mib(self):
        """Guards against an accidental downgrade of the byte cap."""
        from mnemosyne.extraction.longdoc.tree_indexer import MAX_LONGDOC_BYTES
        assert MAX_LONGDOC_BYTES == 50 * 1024 * 1024


# -- ISSUE-0003 T6: benchmark smoke (skip without env) ------------------------


class TestBenchScriptSmoke:
    """AC-1: the bench script exists, is importable, and either runs the smoke
    pass or skips cleanly when pymupdf is absent."""

    def test_bench_script_smoke_pass(self):
        """Run the bench script with --smoke against the committed fixture."""
        repo_root = Path(__file__).resolve().parents[1]
        fixture = repo_root / "tests" / "fixtures" / "longdoc" / "one_page.pdf"
        if not fixture.exists():
            pytest.skip(f"committed fixture missing: {fixture}")
        try:
            import fitz  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            pytest.skip("pymupdf (fitz) not installed; smoke skipped")

        from scripts.bench.longdoc_bench import run_smoke

        report = run_smoke(fixture)
        # Smoke should NOT skip when pymupdf is present and the fixture exists.
        assert report.get("skipped") is not True, (
            f"smoke run unexpectedly skipped: {report}"
        )
        assert "build_seconds" in report
        assert "retrieve_seconds" in report
        # Smoke wall-time sanity: a 1-page build + retrieve should be quick.
        assert report["build_seconds"] < 30, report
        assert report["retrieve_seconds"] < 5, report

    def test_bench_script_skips_without_env(self, monkeypatch, capsys):
        """Without MNEMOSYNE_RUN_BENCHMARKS=1 the full bench prints a skip
        reason and exits 0 (CI-safe)."""
        monkeypatch.delenv("MNEMOSYNE_RUN_BENCHMARKS", raising=False)
        from scripts.bench.longdoc_bench import main

        rc = main([])
        out = capsys.readouterr().out
        assert rc == 0
        assert "skipped" in out
        assert "MNEMOSYNE_RUN_BENCHMARKS" in out

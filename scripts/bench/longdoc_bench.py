#!/usr/bin/env python3
"""SPEC-LONGDOC-001 B-LONGDOC-001: long-doc benchmark harness.

Generates a 50-page PDF and a 100k-token markdown fixture AT RUNTIME into a
temp dir (nothing large is committed), builds a ``LongDocIndexer`` tree, then
runs ``LongDocRetriever.retrieve`` top-5 and prints a JSON timing report.

Targets (typical local hardware):
    - build  < 30s
    - retrieve top-5 < 1s

CI-safety: the script is gated behind ``MNEMOSYNE_RUN_BENCHMARKS=1``. Without
the flag it prints a skip-reason and exits 0 so it can be wired into CI as a
no-op. Large fixtures are runtime-generated only; a small committed
``tests/fixtures/longdoc/one_page.pdf`` is used by the smoke test.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

# Repo-root on sys.path so this runs without `uv run`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Soft-dep: pymupdf. The script skips cleanly when absent.
try:
    import fitz  # type: ignore[import-not-found]  # noqa: F401
    _HAVE_FITZ = True
except ImportError:
    _HAVE_FITZ = False


def _want_full_run(env: Dict[str, str]) -> bool:
    return env.get("MNEMOSYNE_RUN_BENCHMARKS", "") == "1"


def _generate_pdf(out_path: Path, pages: int = 50) -> None:
    """Generate a multi-page PDF at *out_path* via pymupdf.

    Each page carries ~400 words of lorem-ipsum-ish text so the resulting
    document exercises the page splitter and token estimator realistically.
    """
    import fitz  # type: ignore[import-not-found]

    page_text = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit, "
        "sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris "
        "nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in "
        "reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla "
        "pariatur. Excepteur sint occaecat cupidatat non proident, sunt in "
        "culpa qui officia deserunt mollit anim id est laborum. " * 8
    )
    doc = fitz.open()  # type: ignore[attr-defined]
    try:
        for _ in range(pages):
            pg = doc.new_page()  # type: ignore[attr-defined]
            pg.insert_text((72, 72), page_text, fontsize=10)  # type: ignore[attr-defined]
        doc.save(str(out_path))
    finally:
        doc.close()


def _generate_markdown(out_path: Path, target_tokens: int = 100_000) -> None:
    """Generate a markdown fixture of approximately *target_tokens* tokens.

    Uses ``# Heading`` sections of ~500 tokens each. ``_WORDS_PER_TOKEN`` is
    0.75 in the indexer, so we emit ~0.75 * target_tokens words.
    """
    words_per_section = 375  # ~500 tokens per section
    target_words = int(target_tokens * 0.75)
    sections = max(1, target_words // words_per_section)
    body_lines = []
    for i in range(sections):
        body_lines.append(f"# Section {i}\n")
        body_lines.append(" ".join(f"word{j}" for j in range(words_per_section)))
        body_lines.append("")
    out_path.write_text("\n".join(body_lines), encoding="utf-8")


def _bench_one(
    workdir: Path, kind: str, path: Path
) -> Dict[str, Any]:
    """Build the tree for *path* and run a top-5 retrieve; return timings."""
    # Imported here so a missing pymupdf does not break module import.
    from mnemosyne.extraction.longdoc.retriever import LongDocRetriever
    from mnemosyne.extraction.longdoc.tree_indexer import LongDocIndexer
    from mnemosyne.graph.knowledge_graph import KnowledgeGraph

    db_path = workdir / f"bench_{kind}.db"
    kg = KnowledgeGraph(db_path=str(db_path))
    try:
        idx = LongDocIndexer(
            conn=kg.conn, entity_types=["note"], domain="coding",
            raw_root=workdir,
        )
        source_hash = f"bench-{kind}"
        t0 = time.perf_counter()
        tree_id = idx.index_file(path, source_hash=source_hash)
        build_s = time.perf_counter() - t0

        retriever = LongDocRetriever(conn=kg.conn)
        query = "section function feature"
        t1 = time.perf_counter()
        # Run a few retrieves to get a stable median-ish number; we report
        # the mean for the report. Stdlib only — no psutil.
        results = retriever.retrieve(query, source_hash, top_k=5)
        retrieve_s = time.perf_counter() - t1

        return {
            "kind": kind,
            "build_seconds": round(build_s, 4),
            "retrieve_seconds": round(retrieve_s, 4),
            "result_count": len(results),
            "tree_id": tree_id,
            "build_target_seconds": 30,
            "retrieve_target_seconds": 1,
            "build_within_target": build_s < 30,
            "retrieve_within_target": retrieve_s < 1,
        }
    finally:
        kg.close()


def run_full(pages: int, tokens: int) -> Dict[str, Any]:
    """Run the full benchmark: generate fixtures, build, retrieve, report."""
    if not _HAVE_FITZ:
        return {
            "skipped": True,
            "reason": "pymupdf (fitz) not installed; PDF benchmark unavailable",
        }
    with tempfile.TemporaryDirectory(prefix="longdoc_bench_") as tmp:
        workdir = Path(tmp)
        pdf_path = workdir / "bench_50p.pdf"
        md_path = workdir / "bench_100k.md"
        t0 = time.perf_counter()
        _generate_pdf(pdf_path, pages=pages)
        _generate_markdown(md_path, target_tokens=tokens)
        fixture_gen_s = time.perf_counter() - t0

        pdf_result = _bench_one(workdir, "pdf50", pdf_path)
        md_result = _bench_one(workdir, "md100k", md_path)
        return {
            "fixture_gen_seconds": round(fixture_gen_s, 4),
            "pdf_pages": pages,
            "markdown_target_tokens": tokens,
            "results": [pdf_result, md_result],
        }


def run_smoke(fixture_pdf: Path) -> Dict[str, Any]:
    """Smoke run against a small committed fixture (no full generation)."""
    if not fixture_pdf.exists():
        return {"skipped": True, "reason": f"missing fixture {fixture_pdf}"}
    if not _HAVE_FITZ:
        return {
            "skipped": True,
            "reason": "pymupdf (fitz) not installed; smoke run unavailable",
        }
    with tempfile.TemporaryDirectory(prefix="longdoc_smoke_") as tmp:
        workdir = Path(tmp)
        # Copy fixture into the workdir so raw_root validation passes.
        dest = workdir / fixture_pdf.name
        dest.write_bytes(fixture_pdf.read_bytes())
        return _bench_one(workdir, "smoke", dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Long-doc benchmark harness.")
    parser.add_argument(
        "--smoke", action="store_true",
        help="Run a fast smoke pass against the committed 1-page fixture.",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/longdoc/one_page.pdf"),
        help="Path to the small committed PDF for --smoke (relative to repo root).",
    )
    parser.add_argument("--pages", type=int, default=50)
    parser.add_argument("--tokens", type=int, default=100_000)
    args = parser.parse_args(argv)

    env = dict(os.environ)

    if args.smoke:
        fixture = (Path(__file__).resolve().parents[2] / args.fixture)
        report = {"mode": "smoke", **run_smoke(fixture)}
        print(json.dumps(report, indent=2))
        return 0

    if not _want_full_run(env):
        print(
            json.dumps(
                {
                    "skipped": True,
                    "reason": (
                        "MNEMOSYNE_RUN_BENCHMARKS!=1; set it to run the full "
                        "50-page PDF + 100k-token markdown benchmark"
                    ),
                },
                indent=2,
            )
        )
        return 0

    report = {"mode": "full", **run_full(pages=args.pages, tokens=args.tokens)}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

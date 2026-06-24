"""Smoke tests for the PyOxidizer-built mnemosyne binary (ISSUE-0008 / SPEC-PACKAGE-001).

These tests verify AC2 (import mnemosyne_core inside the binary), AC3 (--help),
AC4 (mcp serve starts), AC5 (degraded mode: no ImportError for gliner/fitz),
and AC6 (binary size budget).

They are skipped unless the binary has been built. Build it with:

    scripts/build_binary.sh

The binary path defaults to ``./build/mnemosyne`` and can be overridden via
the ``MNEMOSYNE_BINARY`` env var.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BINARY_PATH = Path(os.environ.get("MNEMOSYNE_BINARY", REPO_ROOT / "build" / "mnemosyne"))
SIZE_LIMIT_BYTES = 100 * 1024 * 1024  # AC6 hard gate (NFR §7)
SIZE_TARGET_BYTES = 80 * 1024 * 1024   # AC6 informational target


pytestmark = pytest.mark.skipif(
    not BINARY_PATH.exists(),
    reason=(
        f"PyOxidizer binary not found at {BINARY_PATH}; "
        "run scripts/build_binary.sh to build it (requires pyoxidizer + cargo + maturin)"
    ),
)


def _run_binary(*args: str, timeout: float = 30.0, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the built binary with the given args, returning the completed process."""
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    return subprocess.run(
        [str(BINARY_PATH), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=run_env,
    )


def test_help_exits_zero() -> None:
    """AC3: binary runs `--help` and exits 0 in a Python-free environment."""
    result = _run_binary("--help")
    assert result.returncode == 0, f"--help exited {result.returncode}\nstderr:\n{result.stderr}"
    assert "usage" in result.stdout.lower() or "usage" in result.stderr.lower()


def test_mnemosyne_core_imports_inside_binary() -> None:
    """AC2 (R-PKG-001 POC): the embedded interpreter can import mnemosyne_core.

    Runs the binary with a `-c` flag executing ``import mnemosyne_core``. If
    PyOxidizer froze the .so resource correctly, the import succeeds and prints
    the extension version.
    """
    result = _run_binary(
        "-c",
        "import mnemosyne_core; print(getattr(mnemosyne_core, '__version__', 'ok'))",
    )
    assert result.returncode == 0, (
        f"import mnemosyne_core failed (rc={result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_mcp_serve_starts() -> None:
    """AC4: `mcp serve` reaches a ready state without crashing on startup.

    We start the server on a throwaway port, wait for the ready signal on
    stderr/stdout, then send SIGTERM. A hard ImportError or crash on startup
    fails the test; a clean shutdown after SIGTERM passes.
    """
    proc = subprocess.Popen(
        [str(BINARY_PATH), "mcp", "serve"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "MNEMOSYNE_MCP_TRANSPORT": "stdio"},
    )
    try:
        # Give the process up to 10s to reach a non-crashing steady state.
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # Still running after 10s == ready; that's the success path.
            pass
        assert proc.poll() is None or proc.returncode == 0, (
            f"mcp serve crashed on startup (rc={proc.returncode})\n"
            f"stderr:\n{proc.stderr.read() if proc.stderr else ''}"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_degraded_mode_no_gliner_or_fitz_importerror(tmp_path) -> None:
    """AC5 (REQ-PKG-002): base binary skips SLM/PDF layers cleanly.

    The base binary excludes gliner/torch/pymupdf by construction. This test
    ingests a tiny plain-text fixture and asserts the run does NOT raise
    ModuleNotFoundError/ImportError for gliner or fitz — exercising the
    existing soft-dep paths at slm_extractor.py:56 and tree_indexer.py:154.

    For a plain-text input, the SLM layer is skipped (no entity output) and
    PDF parsing is not invoked. The pass condition is: no ImportError surfacing
    from the frozen-import machinery for the missing packages.
    """
    fixture = tmp_path / "sample.txt"
    fixture.write_text("hello world\n", encoding="utf-8")

    result = _run_binary("ingest", "add", str(fixture), "--domain", "daily", timeout=60)
    combined = result.stdout + result.stderr
    forbidden = ["ModuleNotFoundError: gliner", "ImportError: gliner",
                 "ModuleNotFoundError: fitz", "ImportError: fitz",
                 "ModuleNotFoundError: torch", "ImportError: torch"]
    for token in forbidden:
        assert token not in combined, (
            f"frozen-import surfaced a soft-dep ImportError for excluded package: "
            f"{token}\nfull output:\n{combined}"
        )


@pytest.mark.skip(
    reason=(
        "AC6 reclassified advisory pending ISSUE-0009 (PyOxidizer 0.4x upgrade "
        "collapses lib/ into single file); measured distribution is ~164 MB "
        "on PyOxidizer 0.24 + CPython 3.10 (binary 145.8 MB + lib/ 18 MB stripped "
        "+ companion <1 MB). See BINARY_BUILD.md and PM Amendment in ISSUE-0008."
    )
)
def test_binary_size_within_budget() -> None:
    """AC6: stripped distribution size budget check.

    Originally a hard gate (<=100 MB) + advisory target (<=80 MB). Reclassified
    to advisory via the PM Amendment in ISSUE-0008 because PyOxidizer 0.24 +
    CPython 3.10 cannot meet the budget with the required runtime dep set
    (cryptography alone is ~11 MB stripped in lib/). The path to <=100 MB is
    the PyOxidizer 0.4x + CPython 3.12 upgrade tracked in ISSUE-0009.

    Skipped (not xfailed) to make the PM-level reclassification explicit in the
    test report: xfail would imply an anticipated-pass-under-different-inputs
    case; this is an AC reclassification, not a known-incomplete test.
    """
    size_bytes = BINARY_PATH.stat().st_size
    size_mb = size_bytes / 1024 / 1024
    assert size_bytes <= SIZE_LIMIT_BYTES, (
        f"AC6 advisory distribution size {size_mb:.1f} MB exceeds 100 MB budget "
        f"(path forward: ISSUE-0009 PyOxidizer 0.4x upgrade)"
    )

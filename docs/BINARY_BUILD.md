# Single-Binary Build (PyOxidizer)

SPEC: SPEC-PACKAGE-001 (REQ-PKG-001, REQ-PKG-002, R-PKG-001, R-PKG-006)
Issue: ISSUE-0008 (PACKAGE-C — T1 POC + T5 linux-x86_64 base binary)

mnemosyne can be packaged into a single static binary via [PyOxidizer](https://pyoxidizer.readthedocs.io/). The base binary embeds CPython 3.12, the trimmed stdlib, the `mnemosyne` package, the `mnemosyne-core` Rust extension, and the lightweight runtime dependencies. It runs `mnemosyne --help`, `mnemosyne mcp serve`, and the full CLI surface with **no Python pre-installed** on the host.

Heavy optional dependencies (`gliner`, `torch`, `transformers`, `pymupdf`/`fitz`) are **deliberately excluded** from the base binary. Their absence is the documented degraded mode (REQ-PKG-002): the SLM layer is skipped and PDF parsing raises `ExtractionError(layer='longdoc')`, matching the existing soft-dep behavior at `mnemosyne/extraction/longdoc/tree_indexer.py:154-163` and `mnemosyne/extraction/semantic/slm_extractor.py:55-60`.

## Prerequisites

| Tool | Pin | Why |
|---|---|---|
| PyOxidizer | `0.24.0` | 0.2x line; the 0.2x→0.3x API renamed several builders (`add_python_module`/`pip_install`) and is NOT drop-in compatible. 0.24 has the best-validated PyO3/`cdylib` embedding story on linux-x86_64 against the SPEC-PERF-001 PyO3 0.20 build. Upgrade to 0.3x is tracked as a follow-up under R-PKG-001. |
| Rust toolchain (`cargo`, `rustc`) | stable | Builds `mnemosyne-core` PyO3 extension via maturin. |
| `maturin` | latest stable | Produces the pre-built `.so` that PyOxidizer embeds. |
| Python 3.12 | 3.12.x | The embedded CPython version (SPEC §5). The host interpreter is only needed for maturin. |

Install (outside ISSUE-0008 scope — recorded for reproducibility):

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
pip install maturin pyoxidizer==0.24.0
```

## Build (linux-x86_64 only in this issue)

```bash
scripts/build_binary.sh
```

The script:

1. Verifies the toolchain (`scripts/build_binary.sh --check` does only this).
2. Builds `mnemosyne-core` via `maturin build --release` and copies the `.so` to `mnemosyne-core/target/wheels/mnemosyne_core.so`.
3. Runs `pyoxidizer build --target-triple x86_64-unknown-linux-gnu`.
4. Copies the stripped binary to `build/mnemosyne` and prints its size.

The resulting binary is at `build/mnemosyne`.

## Smoke + benchmark

```bash
# Size (AC6) + cold-start --help median of 5 (AC7)
scripts/bench_binary.sh build/mnemosyne

# Full pytest smoke (skipped automatically if binary absent)
uv run pytest tests/test_binary_smoke.py -v
```

## Acceptance criteria mapping

| AC | How |
|---|---|
| AC1 | `scripts/build_binary.sh` exits 0; `pyoxidizer build` completes. |
| AC2 | `tests/test_binary_smoke.py::test_mnemosyne_core_imports_inside_binary`. |
| AC3 | `tests/test_binary_smoke.py::test_help_exits_zero` (run in a fresh container with no Python). |
| AC4 | `tests/test_binary_smoke.py::test_mcp_serve_starts`. |
| AC5 | `tests/test_binary_smoke.py::test_degraded_mode_no_gliner_or_fitz_importerror`. |
| AC6 | `scripts/bench_binary.sh` prints `size_status=ok` (<=100 MB hard gate; <=80 MB target advisory). |
| AC7 | `scripts/bench_binary.sh` prints `cold_start_status=ok` (<=300 ms goal, advisory). |
| AC8 | `uv run pytest tests/ --ignore=tests/test_ingest_cli.py -q` — 750-test regression suite green. |

## Fresh-container smoke (manual)

```bash
docker run --rm -v "$PWD/build/mnemosyne:/usr/local/bin/mnemosyne:ro" \
    --entrypoint /usr/local/bin/mnemosyne \
    scratch --help
```

Or, if `scratch` is too bare:

```bash
docker run --rm -v "$PWD/build:/mnt:ro" alpine:latest \
    /mnt/mnemosyne --help
```

Both verify the binary does not depend on a system Python.

## Dependency-set reconciliation (SPEC-PACKAGE-001 §4)

| Dep | Status in `pyproject.toml` | In base binary? | Note |
|---|---|---|---|
| `mcp` | core | yes | |
| `httpx` | `[ingest]` extras | yes | promoted into binary closure; does NOT change `pyproject.toml` |
| `json-repair` | not declared | **no** | SPEC-named but not imported anywhere in `mnemosyne/` (grep-verified 2026-06-23). Omitted from the base binary. If a future commit starts `import json_repair`, add it to `requirements-binary.txt`. |
| `gliner`, `torch`, `transformers` | `[semantic]` extras | no | SLM layer; delivered via extension in PACKAGE-B. |
| `pymupdf` (fitz) | not declared (deliberate soft-dep) | no | PDF layer; delivered via extension in PACKAGE-B. |

## Out of scope for this issue

- Cross-platform matrix (linux-aarch64, darwin-*, windows-*) → ISSUE-0009 (PACKAGE-D).
- Install scripts (`install.sh`, `install.ps1`) → ISSUE-0009.
- CI workflow (`.github/workflows/release-binaries.yml`) → ISSUE-0009.
- cosign signing, notarization, checksum-file generation → ISSUE-0009.
- Extension install/list/remove verbs → PACKAGE-B.

## R-PKG-001 (PyOxidizer + PyO3 fragility)

The T1 POC (`import mnemosyne_core` inside the binary) is the de-risk gate. If the embedded `.so` fails to import, the first lever is `minimize_distribution_independence=False` in `pyoxidizer.bzl` (forces the extension module to load from a real filesystem path rather than the in-memory frozen-import machinery). The second lever is the PyOxidizer version pin (0.24 → 0.3x upgrade requires re-running the POC).

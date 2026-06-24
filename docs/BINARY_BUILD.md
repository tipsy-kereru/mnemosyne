# Single-Binary Build (PyOxidizer)

SPEC: SPEC-PACKAGE-001 (REQ-PKG-001, REQ-PKG-002, R-PKG-001, R-PKG-006)
Issue: ISSUE-0008 (PACKAGE-C — T1 POC + T5 linux-x86_64 base binary)

mnemosyne is packaged into a distributable binary via [PyOxidizer](https://pyoxidizer.readthedocs.io/). The binary embeds CPython, the trimmed stdlib, the `mnemosyne` package, the `mnemosyne-core` Rust extension, and the lightweight runtime dependencies. It runs `mnemosyne --help`, `mnemosyne mcp serve`, and the full CLI surface with **no Python pre-installed** on the host.

Heavy optional dependencies (`gliner`, `torch`, `transformers`, `pymupdf`/`fitz`) are **deliberately excluded** from the base binary. Their absence is the documented degraded mode (REQ-PKG-002): the SLM layer is skipped and PDF parsing is skipped, matching the existing soft-dep behavior at `mnemosyne/extraction/longdoc/tree_indexer.py:154-163` and `mnemosyne/extraction/semantic/slm_extractor.py:55-60`.

## Measured results (linux-x86_64, ISSUE-0008 dev hardware)

| Metric | Value | AC | Status |
|---|---|---|---|
| Binary executable (stripped) | 145.8 MB | — | top-level `build/mnemosyne` |
| `lib/` (extension `.so`s, stripped) | 18 MB | — | cryptography/pydantic_core/sqlalchemy/... |
| Companion dirs (`jsonschema_specifications` + `referencing`) | <1 MB | — | frozen-import workaround |
| **Distribution footprint (binary + lib/ + companion)** | **~164 MB** | AC6 (<=100 MB) | **advisory** — reclassified via PM Amendment; owned by ISSUE-0009 (PyOxidizer 0.4x + CPython 3.12) |
| Cold-start `--help` median of 5 | 107 ms | AC7 (<=300 ms goal) | **pass** |
| `mnemosyne --help` in fresh container | rc=0 | AC3 | **pass** |
| `import mnemosyne_core` inside binary | ok | AC2 (T1 POC) | **pass** |
| `mnemosyne mcp serve` startup | reaches ready state | AC4 | **pass** |
| Degraded-mode ingest (no gliner/fitz) | no ImportError | AC5 | **pass** |
| Regression suite | 860 passed, 4 skipped | AC8 | **pass** |

## Prerequisites

| Tool | Pin | Why |
|---|---|---|
| PyOxidizer | `0.24.0` | 0.2x line; the 0.2x→0.3x API renamed several builders and is NOT drop-in compatible. 0.24 is what the dev environment has installed; upgrade is tracked as a follow-up under R-PKG-001. |
| Rust toolchain (`cargo`, `rustc`) | stable (1.96) | Builds `mnemosyne-core` PyO3 extension via maturin. |
| `maturin` | latest stable (1.14) | Produces the pre-built wheel that PyOxidizer embeds. |
| Python 3.10 | 3.10.x | **Deviation from SPEC §5 (which pins 3.12).** PyOxidizer 0.24 only ships a CPython 3.10.9 distribution for x86_64-unknown-linux-gnu; `python_version="3.12"` and `"3.11"` both fail. See "CPython version deviation" below. |

Install (outside ISSUE-0008 scope — recorded for reproducibility):

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
pip install maturin pyoxidizer==0.24.0
uv python install 3.10     # for maturin + the runtime-deps venv
```

## Build (linux-x86_64 only in this issue)

```bash
# Release build (default): ~164 MB distribution at build/mnemosyne + build/lib/
scripts/build_binary.sh

# Debug build (faster iteration): build/x86_64-unknown-linux-gnu/debug/install/mnemosyne
scripts/build_binary.sh --debug

# Toolchain check only:
scripts/build_binary.sh --check
```

The script:

1. Verifies the toolchain (pyoxidizer, cargo/rustc, maturin, python3.10).
2. Builds `mnemosyne-core` via `maturin build --release --interpreter python3.10 --strip` (CPython 3.10 ABI; matches the PyOxidizer-embedded interpreter).
3. Creates a venv at `mnemosyne-core/build_venv/` with the runtime deps from `requirements-binary.txt`. PyOxidizer consumes this via `read_virtualenv`.
4. Generates `mnemosyne-core/build_venv/fs_files.star` enumerating data files of `FILESYSTEM_PACKAGES` (jsonschema_specifications, referencing) — the frozen-import hazard workaround (see "Frozen-import hazard" below).
5. Runs `pyoxidizer build --release --target-triple x86_64-unknown-linux-gnu`.
6. Copies the binary + `lib/` + filesystem-package dirs to `build/`, then strips the top-level executable AND every `lib/**/*.so` with `strip --strip-all`.

Output layout:

```
build/
├── mnemosyne                           # the executable (145.8 MB stripped)
├── lib/                                # extension modules (.so, stripped) — filesystem fallback
│   ├── mnemosyne_core/                 # the Rust extension
│   ├── cryptography/, pydantic_core/, sqlalchemy/, ...
├── jsonschema_specifications/          # filesystem-shipped (frozen-import hazard)
└── referencing/                        # filesystem-shipped (frozen-import hazard)
```

The binary is NOT a single file — it requires `lib/`, `jsonschema_specifications/`, and `referencing/` alongside it. This is a PyOxidizer 0.24 limitation (Linux can't load `.so` from memory; `importlib.resources.iterdir()` doesn't work on frozen packages). A future PyOxidizer 0.4x upgrade (ISSUE-0009) may collapse these into the binary.

## Smoke + benchmark

```bash
# Size (AC6) + cold-start --help median of 5 (AC7)
scripts/bench_binary.sh

# Full pytest smoke (skipped automatically if binary absent)
MNEMOSYNE_BINARY=build/mnemosyne uv run pytest tests/test_binary_smoke.py -v
```

## CPython version deviation (SPEC §5 vs reality)

SPEC-PACKAGE-001 §5 pins CPython 3.12. PyOxidizer 0.24 only ships a CPython 3.10.9 distribution for x86_64-unknown-linux-gnu; `python_version="3.12"` and `"3.11"` both fail with `could not find default Python distribution`.

Resolution chosen for this issue:

- Build with the bundled CPython 3.10.9. The `mnemosyne` source has no 3.11+ syntax deps (grep-verified: no `tomllib`, `ExceptionGroup`, `except*`, `Self`, `TypeAlias` usage). The `requires-python = ">=3.11"` floor in `pyproject.toml` is a policy floor, not a runtime floor — the package runs cleanly on 3.10.
- The Rust extension is built against CPython 3.10 so the embedded `.so` ABI matches the embedded interpreter (pyo3 0.20, non-abi3).
- The runtime-deps venv is also CPython 3.10 so pure-Python deps match.

Path forward to 3.12: upgrade to PyOxidizer 0.4x (ISSUE-0009 / PACKAGE-D). That requires the 0.3x+ Starlark API migration (renamed builders) plus a re-run of the AC2 `import mnemosyne_core` POC. R-PKG-001 tracks this.

## Frozen-import hazard (R-PKG-001, documented in issue Technical Notes)

PyOxidizer's frozen importer (`OxidizedFinder`) claims modules added via `add_python_resources`. For pure-Python packages this is fine, BUT packages that use `importlib.resources.files().iterdir()` to discover bundled data files at runtime do NOT work when frozen — the frozen importer serves module source but not iter-directory semantics over package data.

Known-affected transitively via `mcp` -> `jsonschema`:

- `jsonschema_specifications` — walks its `schemas/` dir via `importlib.resources.files(__package__).joinpath("schemas").iterdir()` at import time.
- `referencing` — registry populated from `jsonschema_specifications`.

Without a workaround, `mcp serve` crashes on startup with `referencing.exceptions.NoSuchResource: 'http://json-schema.org/draft-03/schema#'`.

Workaround (implemented in `pyoxidizer.bzl` + `scripts/build_binary.sh`):

1. **Filter** these packages out of the frozen resource set returned by `read_virtualenv` (top-level prefix match).
2. **Ship** them as filesystem-relative files via `FileManifest.add_path` (looped over a generated file list in `mnemosyne-core/build_venv/fs_files.star`).
3. **Enable** `module_search_paths = ["$ORIGIN"]` + `filesystem_importer = True` so the path-based finder discovers the filesystem copies at `$ORIGIN/jsonschema_specifications/...`.

The `mnemosyne/cli.py` `_load_dotenv()` function was also patched (frozen-import compatibility): `__file__` is None when the module is loaded via PyOxidizer's frozen importer, so the original `Path(__file__).resolve().parent` crashed on startup. The fix reads `__file__` via `sys.modules[__name__]` and falls back to cwd-based discovery when unavailable. This is a 2-line compatibility shim, not a CLI refactor (ISSUE-0006 owns CLI refactoring).

## Size deviation (AC6 — reclassified advisory via PM Amendment)

The full distribution footprint (binary + `lib/` + companion dirs) is ~164 MB, over the 100 MB budget. The binary alone is 145.8 MB stripped. Breakdown:

- Binary executable: 145.8 MB (embedded CPython 3.10 stdlib + builtin extensions + mnemosyne package source + Rust pyembed crate).
- `lib/` (after `strip --strip-all` on every `.so`): 18 MB (extension modules extracted via filesystem fallback — cryptography 11.4 MB stripped, pydantic_core 3.7 MB, sqlalchemy 3.5 MB, yaml 2.0 MB, greenlet 1.1 MB, rpds 0.9 MB, mnemosyne_core 0.5 MB, cffi 0.3 MB).
- `jsonschema_specifications/` + `referencing/`: <1 MB combined.

Strip applied in `scripts/build_binary.sh::install_binary`:

- Top-level executable: `strip --strip-all` (saves ~7 MB on the 152.9 MB unstripped build).
- Every `lib/**/*.so`: `strip --strip-all` (falls back to `--strip-debug` for `.so`s that reject it; saves ~9 MB — `lib/` was 28 MB unstripped, 18 MB stripped).

Levers applied in `pyoxidizer.bzl` (stdlib trimming):

- `policy.include_test = False` — strips stdlib `test/` package.
- `policy.extension_module_filter = "no-copyleft"` — drops GPL-family stdlib extensions. (`"minimal"` would be smaller but produces a broken `config.c` on PyOxidizer 0.24 that omits `_PyAtExit_Call`, causing a linker error — known 0.24 bug.)

Levers NOT applied (would break functionality):

- `extension_module_filter = "minimal"` — omits `_sqlite3` (knowledge.db), `_ssl`/`_hashlib` (httpx/mcp), `zlib`, etc. Also triggers the linker bug above on 0.24.
- Dropping `cryptography` from the closure — would break mTLS for `httpx`/`mcp` paths that the base binary must serve.

Path forward to <=100 MB: the PyOxidizer 0.4x upgrade (ISSUE-0009) brings a slimmer stdlib embedding story, CPython 3.12 (which has better stdlib trimming hooks), and may collapse `lib/` + companion dirs into the binary proper. AC6 was reclassified from "hard gate" to "advisory, owned by ISSUE-0009" via the PM Amendment in this issue (see `## PM Amendment` in `.harness/issues/ISSUE-0008.md`); the smoke test (`test_binary_size_within_budget`) uses `pytest.mark.skip` with the measured number to make the reclassification explicit in the test report.

## Dependency-set reconciliation (SPEC-PACKAGE-001 §4)

| Dep | Status in `pyproject.toml` | In base binary? | Note |
|---|---|---|---|
| `mcp` | core | yes | |
| `httpx` | `[ingest]` extras | yes | promoted into binary closure; does NOT change `pyproject.toml` |
| `json-repair` | not declared | **no** | SPEC-named but not imported anywhere in `mnemosyne/` (grep-verified 2026-06-23). Omitted from the base binary. If a future commit starts `import json_repair`, add it to `requirements-binary.txt`. |
| `gliner`, `torch`, `transformers` | `[semantic]` extras | no | SLM layer; delivered via extension in PACKAGE-B. |
| `pymupdf` (fitz) | not declared (deliberate soft-dep) | no | PDF layer; delivered via extension in PACKAGE-B. |

## Acceptance criteria mapping

| AC | How | Status |
|---|---|---|
| AC1 | `scripts/build_binary.sh` exits 0; `pyoxidizer build` completes. | pass |
| AC2 | `tests/test_binary_smoke.py::test_mnemosyne_core_imports_inside_binary`. | pass |
| AC3 | `tests/test_binary_smoke.py::test_help_exits_zero` (run in a fresh container with no Python). | pass |
| AC4 | `tests/test_binary_smoke.py::test_mcp_serve_starts`. | pass |
| AC5 | `tests/test_binary_smoke.py::test_degraded_mode_no_gliner_or_fitz_importerror`. | pass |
| AC6 | `scripts/bench_binary.sh` prints `size_status=over_budget` (~164 MB distribution; reclassified advisory via PM Amendment; owned by ISSUE-0009). | advisory (skip) |
| AC7 | `scripts/bench_binary.sh` prints `cold_start_status=ok` (107 ms median; <=300 ms goal). | pass |
| AC8 | `uv run pytest tests/ --ignore=tests/test_ingest_cli.py -q` — 860 tests pass, 4 skipped. | pass |

## Fresh-container smoke (manual)

```bash
docker run --rm -v "$PWD/build:/mnt:ro" alpine:latest \
    /mnt/mnemosyne --help
```

This verifies the binary does not depend on a system Python. (Note: the binary needs `lib/`, `jsonschema_specifications/`, and `referencing/` next to it; the volume mount ships the whole `build/` dir.)

## Out of scope for this issue

- Cross-platform matrix (linux-aarch64, darwin-*, windows-*) → ISSUE-0009 (PACKAGE-D).
- Install scripts (`install.sh`, `install.ps1`) → ISSUE-0009.
- CI workflow (`.github/workflows/release-binaries.yml`) → ISSUE-0009.
- cosign signing, notarization, checksum-file generation → ISSUE-0009.
- CPython 3.12 embedding → ISSUE-0009 (requires PyOxidizer 0.4x upgrade).
- Collapsing `lib/` + filesystem-package dirs into a true single-file binary → ISSUE-0009.
- Extension install/list/remove verbs → PACKAGE-B.

## R-PKG-001 (PyOxidizer + PyO3 fragility)

The T1 POC (`import mnemosyne_core` inside the binary) is the de-risk gate and it passes. The embedded `.so` is consumed via `pip_install` of the maturin wheel, which places it at the correct import path (`mnemosyne_core/mnemosyne_core.cpython-310-x86_64-linux-gnu.so`) inside the embedded interpreter's filesystem fallback (`lib/`).

The PyOxidizer 0.24 → 0.4x upgrade (ISSUE-0009) is the primary follow-up: it unlocks CPython 3.12, brings a slimmer stdlib embedding story (path to <=100 MB), and may collapse the filesystem-fallback dirs into the binary proper.

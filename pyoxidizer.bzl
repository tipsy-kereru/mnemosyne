# PyOxidizer build configuration for the mnemosyne single-binary distribution.
#
# SPEC: SPEC-PACKAGE-001 (REQ-PKG-001, REQ-PKG-002, R-PKG-006)
# Issue: ISSUE-0008 (PACKAGE-C — T1 POC + T5 linux-x86_64 base binary)
#
# This file is Starlark consumed by `pyoxidizer build`. It embeds:
#   * CPython 3.12 (PyOxidizer-managed distribution)
#   * Python stdlib, trimmed per R-PKG-006 (no test/, idlelib, tkinter, ensurepip)
#   * the `mnemosyne` Python package (from the local checkout)
#   * the `mnemosyne-core` Rust extension, as a *pre-built* shared object produced
#     by `maturin build --release` (consumed here as a resource, NOT rebuilt —
#     this keeps the PyOxidizer iteration loop fast and avoids a Rust toolchain
#     dependency inside PyOxidizer's own build pipeline)
#   * the lightweight runtime deps: networkx, sqlalchemy, python-dateutil,
#     pyyaml, python-dotenv, mcp (and their transitive pure-Python closure)
#
# Excluded by design (REQ-PKG-002 degraded mode): gliner, torch, transformers,
# pymupdf (fitz). These are delivered post-install via the extension sidecar
# mechanism (PACKAGE-B) and are absent from the base binary on purpose.
#
# ----------------------------------------------------------------------------
# PyOxidizer version pin (R-PKG-001 / PM open question)
# ----------------------------------------------------------------------------
# Pin: PyOxidizer 0.24.0 (the last stable 0.2x line, released 2023-08).
#
# Why 0.24 and not 0.3x:
#   * The 0.2x → 0.3x line renamed several `PythonExecutable` builder methods
#     (e.g. `add_python_module` → `add_python_modules`, `pip_install` →
#     `add_python_packages`, and the resource-visitor API changed). The two
#     lines are NOT drop-in compatible.
#   * 0.24.0 is the version with the most battle-tested PyO3/`cdylib` embedding
#     story on linux-x86_64 and matches what SPEC-PERF-001 (PyO3 0.20 /
#     `extension-module` non-abi3) was validated against.
#   * Upgrading to 0.3x is tracked as a follow-up (R-PKG-001) and requires
#     re-running the AC2 `import mnemosyne_core` POC.
#
# Install (outside this issue's scope — recorded for reproducibility):
#   pip install pyoxidizer==0.24.0
#
# Build (target = linux-x86_64 only in this issue; cross-platform → ISSUE-0009):
#   pyoxidizer build --target-triple x86_64-unknown-linux-gnu
#
# The resulting binary lands at:
#   build/x86_64-unknown-linux-gnu/release/install/mnemosyne
# and is copied to build/mnemosyne by scripts/build_binary.sh.

# ---- CPython distribution ---------------------------------------------------
# Pin CPython 3.12.x explicitly (SPEC §5 assumption, R-PKG-002 torch support).
# PyOxidizer resolves a known-good 3.12 distribution; the patch version follows
# the PyOxidizer 0.24 distribution manifest (currently 3.12.1).
PYTHON_VERSION = "3.12"

# Pre-built mnemosyne-core shared object produced by maturin. This path is
# written by `scripts/build_binary.sh` (which runs `maturin build --release`
# first) before invoking `pyoxidizer build`. PyOxidizer consumes it as a
# `PythonExtensionModule` resource and embeds the `.so` bytes into the binary,
# so no Rust toolchain is needed at PyOxidizer build time.
MNEMOSYNE_CORE_SO = Label("mnemosyne-core/target/wheels/mnemosyne_core.so")


def make_distribution():
    # Note: this function is intentionally a thin factory; the real executable
    # is assembled by make_exe below. `make_distribution` is the conventional
    # PyOxidizer entry point.
    return make_exe()


def make_exe():
    # 1. Start from a CPython 3.12 distribution with default packaging policy.
    dist = default_python_distribution(python_version=PYTHON_VERSION)

    # 2. Trim the stdlib per R-PKG-006 to pull the binary under the 80 MB
    #    target. These packages are either never imported by mnemosyne
    #    (idlelib, tkinter, turtle) or purely developer-facing (test/,
    #    __pycache__, ensurepip). Removing them shaves ~15-20 MB off the
    #    base binary.
    python_config = dist.make_python_interpreter_config()
    python_config.run_command = "import mnemosyne.cli; mnemosyne.cli.main()"

    # 3. Build the packaged resources (mnemosyne package + pure-Python deps
    #    from requirements-metabase). We exclude the heavy optional deps
    #    (gliner, torch, transformers, pymupdf) at the requirements-file level
    #    so they never enter the resource set.
    exe = dist.to_python_executable(
        name="mnemosyne",
        config=python_config,
    )

    # 4. Add the mnemosyne Python package itself. `add_python_resources` walks
    #    the local source tree and freezes each `.py` into the binary.
    exe.add_python_resources(
        exe.pip_install(
            ["-r", Label("requirements-binary.txt"), "."],
        )
    )

    # 5. Embed the pre-built Rust extension. `add_python_resource` takes a
    #    single resource; the `.so` is mapped to its import path
    #    `mnemosyne.mnemosyne_core` (matches setup.py RustExtension target).
    #    This is the AC2 POC (R-PKG-001 de-risk): if the embedded interpreter
    #    can `import mnemosyne_core`, the PyO3/PyOxidizer bundling works.
    exe.add_python_resource(
        exe.read_python_resource(
            "mnemosyne.mnemosyne_core",
            MNEMOSYNE_CORE_SO,
        )
    )

    # 6. The frozen-import bootstrap must NOT fail on the soft-dep lazy
    #    imports (gliner at slm_extractor.py:56, fitz at tree_indexer.py:154).
    #    PyOxidizer freezes only what we add above, so gliner/fitz are simply
    #    absent and the existing try/except ImportError paths handle them —
    #    REQ-PKG-002 degraded mode is the *default* state of this binary.
    return exe


# PyOxidizer 0.24 entry hook. `register_target` declares named build targets;
# the default target is used by `pyoxidizer build` with no `--target-triple`
# override beyond the host.
register_target(
    "mnemosyne",
    make_distribution,
)
resolve_targets()

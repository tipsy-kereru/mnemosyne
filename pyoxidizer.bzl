# PyOxidizer build configuration for the mnemosyne single-binary distribution.
#
# SPEC: SPEC-PACKAGE-001 (REQ-PKG-001, REQ-PKG-002, R-PKG-006)
# Issue: ISSUE-0008 (PACKAGE-C — T1 POC + T5 linux-x86_64 base binary)
#
# This file is Starlark consumed by `pyoxidizer build`. It embeds:
#   * CPython (PyOxidizer-managed distribution)
#   * Python stdlib, trimmed per R-PKG-006 (no test/)
#   * the `mnemosyne` Python package (via read_package_root)
#   * the `mnemosyne-core` Rust extension, as a *pre-built* wheel produced
#     by `maturin build --release` (consumed via pip_install, NOT rebuilt)
#   * the lightweight runtime deps from a pre-built venv (networkx, sqlalchemy,
#     python-dateutil, pyyaml, python-dotenv, mcp, httpx + transitive closure)
#   * data-heavy packages that PyOxidizer's frozen importer cannot serve via
#     `importlib.resources.iterdir()` (jsonschema_specifications, referencing)
#     are shipped as filesystem-relative files alongside the binary.
#
# Excluded by design (REQ-PKG-002 degraded mode): gliner, torch, transformers,
# pymupdf (fitz). These are delivered post-install via the extension sidecar
# mechanism (PACKAGE-B) and are absent from the base binary on purpose.
#
# ----------------------------------------------------------------------------
# PyOxidizer version pin (R-PKG-001 / PM open question)
# ----------------------------------------------------------------------------
# Pin: PyOxidizer 0.24.0 (the last stable 0.2x line).
#
# Why 0.24 and not 0.3x/0.4x:
#   * 0.24 is the version installed in the dev environment (installed by the
#     user ahead of this run). The 0.2x → 0.3x line renamed several
#     `PythonExecutable` builder methods and changed the resource-visitor API;
#     the two lines are NOT drop-in compatible.
#   * Upgrading to 0.3x/0.4x is tracked as a follow-up (R-PKG-001) and is the
#     path to CPython 3.12 embedding (see deviation note below).
#
# ----------------------------------------------------------------------------
# CPython version deviation (SPEC vs reality — documented, not blocking)
# ----------------------------------------------------------------------------
# SPEC-PACKAGE-001 §5 pins CPython 3.12. PyOxidizer 0.24 only ships a default
# CPython 3.10.9 distribution for x86_64-unknown-linux-gnu; `python_version="3.12"`
# and `"3.11"` both fail with "could not find default Python distribution".
#
# Resolution chosen for this issue (ISSUE-0008 T1/T5):
#   * Build with the bundled CPython 3.10.9 to land a working linux-x86_64 base
#     binary within scope. The mnemosyne source has no 3.11+ syntax deps
#     (grep-verified: no tomllib/ExceptionGroup/Self/TypeAlias usage), so the
#     binary runs fine on 3.10; the `requires-python = ">=3.11"` in
#     pyproject.toml is a policy floor, not a runtime floor.
#   * The Rust extension is built against CPython 3.10 (`maturin build
#     --release --interpreter python3.10`) so the embedded `.so` ABI matches
#     the embedded interpreter (pyo3 0.20, non-abi3).
#   * The runtime venv used for dependency embedding is also CPython 3.10
#     (`mnemosyne-core/build_venv/`) so pure-Python deps match the interpreter.
#   * Upgrading to PyOxidizer 0.4x + CPython 3.12 is ISSUE-0009 (PACKAGE-D)
#     follow-up scope: it requires the 0.3x+ Starlark API migration + a
#     re-run of the AC2 `import mnemosyne_core` POC.
#
# ----------------------------------------------------------------------------
# Frozen-import hazard workaround (R-PKG-001 / Technical Notes)
# ----------------------------------------------------------------------------
# PyOxidizer's frozen importer (OxidizedFinder) claims modules added via
# `add_python_resources`. For pure-Python packages this is fine, BUT packages
# that use `importlib.resources.files().iterdir()` to discover bundled data
# files do NOT work when frozen — the frozen importer serves module source
# but not iter-directory semantics over package data.
#
# Known-affected: `jsonschema_specifications` (uses importlib.resources to
# walk its `schemas/` dir at import time, triggered transitively via
# `mcp` -> `jsonschema`). Without the workaround below, `mcp serve` crashes
# on startup with `referencing.exceptions.NoSuchResource`.
#
# Workaround: (1) filter these packages out of the frozen resource set,
# (2) ship them as filesystem-relative files via `add_path`, (3) add `$ORIGIN`
# to `module_search_paths` so the path-based finder discovers them.
#
# Build (target = linux-x86_64 only in this issue; cross-platform → ISSUE-0009):
#   scripts/build_binary.sh
#
# The resulting binary lands at:
#   build/x86_64-unknown-linux-gnu/debug/install/mnemosyne  (debug)
#   build/x86_64-unknown-linux-gnu/release/install/mnemosyne (release, default)
# and is copied to build/mnemosyne by scripts/build_binary.sh.

# Packages that must be filesystem-relative (NOT frozen) because they use
# importlib.resources.files().iterdir() at runtime. See hazard note above.
# Populated/verified by scripts/build_binary.sh.
FILESYSTEM_PACKAGES = ["jsonschema_specifications", "referencing"]

# File list for FILESYSTEM_PACKAGES, populated by scripts/build_binary.sh
# at `mnemosyne-core/build_venv/fs_files.star`. `load()` must be at module
# top level per the Starlark spec. The file is generated before pyoxidizer
# is invoked; if absent, FS_FILES stays empty and the build proceeds without
# the filesystem workaround (mcp serve will fail at runtime — AC4).
FS_FILES = []
FS_STRIP_PREFIX = ""
# Path to the pre-built mnemosyne-core wheel. Parameterized per platform
# (ISSUE-0009 PACKAGE-D): the wheel filename encodes the ABI tag
# (manylinux_2_34_x86_64, manylinux_2_34_aarch64, macosx_*_arm64, win_amd64).
# scripts/build_binary.sh writes mnemosyne-core/wheel_path.star after `maturin build`.
WHEEL_PATH = "mnemosyne-core/target/wheels/mnemosyne_core-0.1.0-cp310-cp310-manylinux_2_34_x86_64.whl"
load("mnemosyne-core/build_venv/fs_files.star", "FS_FILES")
load("mnemosyne-core/build_venv/fs_prefix.star", "FS_STRIP_PREFIX")
load("mnemosyne-core/wheel_path.star", "WHEEL_PATH")


def make_exe():
    # 1. Start from the bundled CPython distribution. PyOxidizer 0.24 default
    #    for x86_64-unknown-linux-gnu is CPython 3.10.9 (see deviation note
    #    above).
    dist = default_python_distribution()

    # 2. Packaging policy. `include_test = False` strips the stdlib `test/`
    #    package (R-PKG-006). Filesystem-relative fallback lets extension
    #    modules (`.so`) load on Linux (in-memory loading is Windows-only).
    policy = dist.make_python_packaging_policy()
    policy.include_test = False
    # Trim stdlib extension modules. "no-copyleft" drops GPL-family extensions
    # (smaller, license-clean). We do NOT use "minimal" — on PyOxidizer 0.24 it
    # produces a broken config.c that omits `_PyAtExit_Call`, causing a linker
    # error (R-PKG-001 / R-PKG-006). "all" would ship everything; "no-copyleft"
    # is the smallest filter that still links cleanly and keeps the extensions
    # mnemosyne needs (_sqlite3, _ssl, _hashlib, zlib, etc).
    policy.extension_module_filter = "no-copyleft"
    policy.resources_location = "in-memory"
    policy.resources_location_fallback = "filesystem-relative:lib"
    policy.file_scanner_classify_files = True
    policy.allow_files = True
    policy.include_classified_resources = True
    policy.include_non_distribution_sources = True
    policy.include_distribution_resources = True

    # 3. Interpreter config. We use `run_command` (NOT `run_module`) so the
    #    binary supports BOTH invocation modes:
    #      * `mnemosyne --help` / `mnemosyne ingest add ...`  -> CLI mode
    #      * `mnemosyne -c "import mnemosyne_core; ..."        -> interpreter mode (AC2 POC)
    #    A `run_module`-only config would make `-c` unreachable (argparse
    #    consumes it as a subcommand). The dispatcher below peeks at argv[1]:
    #    if `-c`, exec the code; otherwise delegate to mnemosyne.cli.main().
    #
    #    `module_search_paths = ["$ORIGIN"]` + `filesystem_importer = True`
    #    enable the path-based finder to discover FILESYSTEM_PACKAGES shipped
    #    alongside the binary (frozen-import hazard workaround).
    python_config = dist.make_python_interpreter_config()
    python_config.module_search_paths = ["$ORIGIN"]
    python_config.filesystem_importer = True
    python_config.run_command = "import sys\nargv = list(sys.argv)\nif len(argv) > 1 and argv[1] == '-c':\n    code = argv[2] if len(argv) > 2 else ''\n    sys.argv = ['mnemosyne-c'] + argv[3:]\n    exec(compile(code, '<command>', 'exec'), {'__name__': '__main__'})\nelse:\n    from mnemosyne import cli\n    sys.argv = ['mnemosyne'] + argv[1:]\n    cli.main()\n"

    exe = dist.to_python_executable(
        name="mnemosyne",
        packaging_policy=policy,
        config=python_config,
    )

    # 4. Embed the pre-built Rust extension via pip_install of the wheel. This
    #    is the AC2 POC (R-PKG-001 de-risk): pip_install places the `.so` at
    #    the correct import path inside the embedded interpreter.
    exe.add_python_resources(
        exe.pip_install([WHEEL_PATH])
    )

    # 5. Embed pure-Python runtime deps from the pre-built venv. We filter OUT
    #    FILESYSTEM_PACKAGES (they are shipped via add_path in make_install to
    #    work around the frozen-import hazard). read_virtualenv returns mixed
    #    resource types; we check the package prefix on each.
    resources = exe.read_virtualenv(path="mnemosyne-core/build_venv")
    filtered = []
    for r in resources:
        # Resource name is "pkg" or "pkg.subpkg..." — check prefix match.
        name = getattr(r, "name", "")
        # Skip if this resource's top-level package is in FILESYSTEM_PACKAGES.
        # We use startswith + boundary check to avoid matching e.g. "foo_jsonschema_specifications".
        skip = False
        for pkg in FILESYSTEM_PACKAGES:
            if name == pkg or name.startswith(pkg + ".") or name.startswith(pkg + "/"):
                skip = True
                break
        if skip:
            continue
        filtered.append(r)
    exe.add_python_resources(filtered)

    # 6. Add the mnemosyne package itself via read_package_root (NOT pip_install).
    #    The local pyproject.toml declares `requires-python = ">=3.11"`, which
    #    would block pip install against the embedded 3.10 interpreter. The
    #    package has no 3.11+ syntax deps (grep-verified). `path` is the PARENT
    #    dir of the package ("."), per the PyOxidizer 0.24 read_package_root
    #    contract.
    exe.add_python_resources(
        exe.read_package_root(
            path=".",
            packages=["mnemosyne"],
        )
    )

    return exe


def make_install(exe):
    # FileManifest is PyOxidizer 0.24's install-layout primitive. We place the
    # built executable at the install root, then add FILESYSTEM_PACKAGES as
    # individual files so the path-based finder serves them at runtime.
    #
    # `add_path` only accepts a single file (not a directory), so the build
    # script pre-populates a Starlark snippet at
    # `mnemosyne-core/build_venv/fs_files.star` enumerating every file under
    # each FILESYSTEM_PACKAGES directory. See scripts/build_binary.sh.
    files = FileManifest()
    files.add_python_resource(".", exe)

    # fs_files.star is loaded at module top-level (Starlark requires `load()`
    # at top level). It defines FS_FILES = [...]. We iterate it here.
    # See the CPython version deviation + frozen-import hazard notes above.
    for p in FS_FILES:
        files.add_path(path=p, strip_prefix=FS_STRIP_PREFIX)

    return files


# PyOxidizer 0.24 entry hooks. `register_target` declares named build targets;
# `default=True` on `install` makes it the target built by `pyoxidizer build`.
register_target("exe", make_exe)
register_target("install", make_install, depends=["exe"], default=True)
resolve_targets()

#!/usr/bin/env bash
# Build the mnemosyne single-binary distribution via PyOxidizer.
#
# Targets: linux-x86_64 (native, ISSUE-0008), linux-aarch64, darwin-arm64,
# darwin-x86_64, windows-x86_64 (ISSUE-0009 / PACKAGE-D).
# The 5-platform matrix + install scripts + CI are ISSUE-0009 (PACKAGE-D).
#
# Pipeline (T1 POC + T5 base binary, REQ-PKG-001):
#   1. Verify toolchain (pyoxidizer, cargo/rustc, maturin, python3.10).
#   2. Build mnemosyne-core Rust extension via maturin for CPython 3.10
#      (PyOxidizer 0.24 ships a 3.10.9 distribution; see pyoxidizer.bzl
#      CPython version deviation note).
#   3. Create a venv at mnemosyne-core/build_venv with the runtime deps from
#      requirements-binary.txt. PyOxidizer consumes this via read_virtualenv.
#   4. Generate fs_files.star enumerating data files of FILESYSTEM_PACKAGES
#      (jsonschema_specifications, referencing) — frozen-import workaround.
#   5. pyoxidizer build --target-triple ${TARGET_TRIPLE} (release).
#   6. Copy the stripped binary to build/mnemosyne. Print size (AC6).
#
# Usage:
#   scripts/build_binary.sh            # build + copy + size report
#   scripts/build_binary.sh --check    # only verify toolchain availability
#   scripts/build_binary.sh --debug    # build debug (faster, larger binary)
#
# Environment:
#   TARGET_TRIPLE       (default: x86_64-unknown-linux-gnu; ISSUE-0009 matrix)
#   PYOXIDIZER_VERSION  (default: 0.24.0; see pin comment in pyoxidizer.bzl)
#   PYTHON_VERSION      (default: 3.10; PyOxidizer 0.24 constraint)
set -euo pipefail

PYTHON_VERSION="${PYTHON_VERSION:-3.10}"
PYOXIDIZER_VERSION="${PYOXIDIZER_VERSION:-0.24.0}"
BUILD_MODE="${BUILD_MODE:-release}"
# Target triple parameterization (ISSUE-0009 PACKAGE-D matrix).
#   linux-x86_64   -> x86_64-unknown-linux-gnu
#   linux-aarch64  -> aarch64-unknown-linux-gnu
#   darwin-x86_64  -> x86_64-apple-darwin
#   darwin-arm64   -> aarch64-apple-darwin
#   windows-x86_64 -> x86_64-pc-windows-msvc
TARGET_TRIPLE="${TARGET_TRIPLE:-x86_64-unknown-linux-gnu}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build"
VENV_DIR="${REPO_ROOT}/mnemosyne-core/build_venv"
WHEELS_DIR="${REPO_ROOT}/mnemosyne-core/target/wheels"

err() { printf 'build_binary.sh: ERROR: %s\n' "$*" >&2; }
log() { printf 'build_binary.sh: %s\n' "$*"; }

check_toolchain() {
    local missing=0
    for tool in pyoxidizer cargo rustc maturin; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            err "missing required tool: $tool"
            missing=1
        fi
    done
    # Locate python3.10 via uv (preferred) or system PATH.
    local py_bin
    py_bin="$(command -v python${PYTHON_VERSION} || true)"
    if [[ -z "$py_bin" ]] && command -v uv >/dev/null 2>&1; then
        py_bin="$(uv python find "${PYTHON_VERSION}" 2>/dev/null || true)"
    fi
    if [[ -z "$py_bin" ]]; then
        err "missing required interpreter: python${PYTHON_VERSION}"
        err "install via: uv python install ${PYTHON_VERSION}"
        missing=1
    fi
    if [[ "$missing" -ne 0 ]]; then
        cat >&2 <<EOF

To install the toolchain (outside ISSUE-0008 scope — recorded for repro):

  # Rust + maturin (PyO3 build of mnemosyne-core)
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source "\$HOME/.cargo/env"
  pip install maturin

  # Python 3.10 (PyOxidizer 0.24 constraint)
  uv python install ${PYTHON_VERSION}

  # PyOxidizer (pin: see pyoxidizer.bzl)
  pip install pyoxidizer==${PYOXIDIZER_VERSION}

Re-run this script after the toolchain is on PATH.
EOF
        return 1
    fi
    log "toolchain OK (pyoxidizer $(pyoxidizer --version 2>&1 | head -1), python${PYTHON_VERSION} at ${py_bin})"
    return 0
}

build_rust_extension() {
    log "building mnemosyne-core via maturin (interpreter: python${PYTHON_VERSION})"
    mkdir -p "${WHEELS_DIR}"
    local py_bin
    py_bin="$(command -v python${PYTHON_VERSION} || uv python find "${PYTHON_VERSION}")"
    (cd "${REPO_ROOT}/mnemosyne-core" && \
        PATH="$(dirname "${py_bin}"):$PATH" maturin build --release --interpreter "${py_bin}" --strip)
    log "rust extension wheel built under ${WHEELS_DIR}"
    # Write wheel_path.star so pyoxidizer.bzl picks the right per-platform wheel
    # (maturin names the wheel with the host ABI tag). ISSUE-0009 PACKAGE-D.
    local wheel
    wheel="$(ls "${WHEELS_DIR}"/mnemosyne_core-*.whl 2>/dev/null | head -1 || true)"
    if [[ -z "${wheel}" ]]; then
        err "no mnemosyne_core wheel found under ${WHEELS_DIR}"
        return 1
    fi
    wheel="$(cd "${WHEELS_DIR}" && pwd)/$(basename "${wheel}")"
    # PyOxidizer's embedded pip runs as a NATIVE Windows process and cannot
    # resolve MSYS/git-bash mount paths (/d/a/...): it prepends the drive
    # letter and produces D:\d\a\... (drive doubling). Convert to a mixed-mode
    # Windows path (D:/a/.../foo.whl) so pip resolves the file correctly.
    # Mixed mode keeps forward slashes, avoiding backslash-escape headaches in
    # the STAR string literal.
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)
            if command -v cygpath >/dev/null 2>&1; then
                wheel="$(cygpath -m "${wheel}")"
            fi
            ;;
    esac
    cat > "${REPO_ROOT}/mnemosyne-core/wheel_path.star" <<EOF
# AUTO-GENERATED by scripts/build_binary.sh — per-platform wheel path.
# Lives outside build_venv so it survives build_dependency_venv's `rm -rf`.
WHEEL_PATH = "${wheel}"
EOF
    log "wheel_path.star -> ${wheel}"
}

build_dependency_venv() {
    log "creating runtime-deps venv at ${VENV_DIR} (python${PYTHON_VERSION})"
    local py_bin
    py_bin="$(command -v python${PYTHON_VERSION} || uv python find "${PYTHON_VERSION}")"
    rm -rf "${VENV_DIR}"
    "${py_bin}" -m venv "${VENV_DIR}"
    # venv layout differs by platform: Windows uses Scripts/ + Lib/site-packages,
    # everyone else uses bin/ + lib/python<X>/site-packages. Detect once.
    local venv_bin_dir venv_sp_dir
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)
            venv_bin_dir="${VENV_DIR}/Scripts"
            venv_sp_dir="${VENV_DIR}/Lib/site-packages"
            ;;
        *)
            venv_bin_dir="${VENV_DIR}/bin"
            venv_sp_dir="${VENV_DIR}/lib/python${PYTHON_VERSION}/site-packages"
            ;;
    esac
    local venv_python
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) venv_python="${venv_bin_dir}/python.exe" ;;
        *)                    venv_python="${venv_bin_dir}/python" ;;
    esac
    # Invoke pip via 'python -m pip' rather than the pip script: Windows
    # refuses to upgrade pip in-place when called as the pip launcher
    # ("To modify pip, please run: ... python.exe -m pip ..."), and the
    # module form is uniformly safe on every platform.
    "${venv_python}" -m pip install --quiet --upgrade pip
    "${venv_python}" -m pip install --quiet -r "${REPO_ROOT}/requirements-binary.txt"
    log "venv populated ($(ls "${venv_sp_dir}" | wc -l) top-level packages)"

    # Generate fs_files.star enumerating data files of FILESYSTEM_PACKAGES.
    # These packages use importlib.resources.files().iterdir() at runtime,
    # which PyOxidizer's frozen importer cannot serve; we ship them as
    # filesystem-relative files alongside the binary instead.
    local sp="${venv_sp_dir}"
    local star="${VENV_DIR}/fs_files.star"
    {
        printf '# AUTO-GENERATED by scripts/build_binary.sh — do not edit.\n'
        printf '# Lists data files of FILESYSTEM_PACKAGES for make_install.\n'
        printf '# Paths are absolute; strip_prefix in pyoxidizer.bzl must match.\n'
        printf 'FS_FILES = [\n'
        for pkg in jsonschema_specifications referencing; do
            pkgdir="${sp}/${pkg}"
            [[ -d "${pkgdir}" ]] || continue
            while IFS= read -r -d '' f; do
                # Skip __pycache__ and tests/ subdirs.
                case "$f" in
                    *__pycache__*|*/tests/*) continue ;;
                esac
                # PyOxidizer runs FileManifest.add_path as a native Windows
                # process and cannot resolve MSYS mount paths (/d/a/...).
                # Convert to mixed-mode (D:/a/...) on Windows runners.
                case "$(uname -s)" in
                    MINGW*|MSYS*|CYGWIN*)
                        if command -v cygpath >/dev/null 2>&1; then
                            f="$(cygpath -m "$f")"
                        fi
                        ;;
                esac
                printf '    "%s",\n' "$f"
            done < <(find "${pkgdir}" -type f -print0)
        done
        printf ']\n'
    } > "${star}"
    # Also write the strip prefix so pyoxidizer.bzl can read it via load().
    # Must be in the same path form as FS_FILES entries (mixed-mode on Windows)
    # so strip_prefix actually matches.
    local prefix_for_star="${sp}/"
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)
            if command -v cygpath >/dev/null 2>&1; then
                prefix_for_star="$(cygpath -m "${sp}")/"
            fi
            ;;
    esac
    cat > "${VENV_DIR}/fs_prefix.star" <<EOF
# AUTO-GENERATED — strip_prefix matching FS_FILES absolute paths.
FS_STRIP_PREFIX = "${prefix_for_star}"
EOF
    log "fs_files.star generated ($(grep -c '    "' "${star}") files, prefix ${prefix_for_star})"
}

bake_version() {
    # The frozen binary has no dist-info, so importlib.metadata.version() fails
    # at runtime and __init__ falls back. Bake the pyproject version into a
    # module the binary ships, so 'mnemosyne --version' reports the real tag.
    local ver
    ver="$(grep -m1 '^version' "${REPO_ROOT}/pyproject.toml" | sed -E 's/.*"([^"]+)".*/\1/')"
    if [[ -z "${ver}" ]]; then
        err "could not read version from pyproject.toml"
        return 1
    fi
    printf '# AUTO-GENERATED by scripts/build_binary.sh — do not edit.\n__version__ = "%s"\n' "${ver}" \
        > "${REPO_ROOT}/mnemosyne/_version.py"
    log "baked version ${ver} -> mnemosyne/_version.py"
}

bake_skill() {
    # SKILL.md is a non-Python data file the frozen importer cannot serve via
    # importlib.resources (ValueError). Bake its content into a Python string
    # module so 'skill install' can write it to the target agent dir.
    local src="${REPO_ROOT}/mnemosyne/skills/SKILL.md"
    if [[ ! -f "${src}" ]]; then
        err "SKILL.md not found at ${src}"
        return 1
    fi
    python - "$src" > "${REPO_ROOT}/mnemosyne/_skill_bundled.py" <<'PY'
import json, pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
# json.dumps yields a valid Python string literal for any content (handles
# quotes, backslashes, newlines) — no manual escaping pitfalls.
print("# AUTO-GENERATED by scripts/build_binary.sh — do not edit.")
print("SKILL_MD = " + json.dumps(text))
PY
    log "baked SKILL.md -> mnemosyne/_skill_bundled.py"
}

run_pyoxidizer() {
    local mode_arg=()
    # PyOxidizer 0.24 defaults to debug builds. Pass --release for release.
    if [[ "${BUILD_MODE}" == "release" ]]; then
        mode_arg=(--release)
    fi
    # Defensively clear the PyOxidizer output tree so incremental caching can
    # never serve a stale mnemosyne package from a previous build (we saw
    # --version report an old hardcoded value when a prior build's artifacts
    # lingered). CI runners are fresh, but this also protects local re-runs.
    rm -rf "${REPO_ROOT}/build"
    log "pyoxidizer build (target: ${TARGET_TRIPLE}, mode: ${BUILD_MODE})"
    (cd "${REPO_ROOT}" && \
        pyoxidizer build --target-triple "${TARGET_TRIPLE}" "${mode_arg[@]}")
}

install_binary() {
    local src
    src="${REPO_ROOT}/build/${TARGET_TRIPLE}/${BUILD_MODE}/install/mnemosyne"
    if [[ ! -f "${src}" ]]; then
        # PyOxidizer may produce under release/ even when requested as default.
        src="${REPO_ROOT}/build/${TARGET_TRIPLE}/release/install/mnemosyne"
    fi
    # Windows cross-compiles produce mnemosyne.exe.
    if [[ ! -f "${src}" ]]; then
        src="${REPO_ROOT}/build/${TARGET_TRIPLE}/${BUILD_MODE}/install/mnemosyne.exe"
    fi
    if [[ ! -f "${src}" ]]; then
        err "pyoxidizer did not produce a binary under build/${TARGET_TRIPLE}/*/install/"
        return 1
    fi
    mkdir -p "${BUILD_DIR}"
    # Copy the binary + the filesystem-relative lib/ dir + FILESYSTEM_PACKAGES.
    cp -f "${src}" "${BUILD_DIR}/mnemosyne"
    local src_install
    src_install="$(dirname "${src}")"
    # lib/ contains extension modules (.so) extracted by the filesystem fallback.
    if [[ -d "${src_install}/lib" ]]; then
        rm -rf "${BUILD_DIR}/lib"
        cp -r "${src_install}/lib" "${BUILD_DIR}/lib"
    fi
    # FILESYSTEM_PACKAGES directories (jsonschema_specifications, referencing).
    for pkg in jsonschema_specifications referencing; do
        if [[ -d "${src_install}/${pkg}" ]]; then
            rm -rf "${BUILD_DIR}/${pkg}"
            cp -r "${src_install}/${pkg}" "${BUILD_DIR}/${pkg}"
        fi
    done
    chmod +x "${BUILD_DIR}/mnemosyne"
    # strip is host-toolchain-specific. Linux binutils `--strip-all` works on
    # ELF; macOS `strip -x` removes local symbols; Windows .exe is left as-is
    # (skipping strip on PE is harmless). Gate by TARGET_TRIPLE prefix so the
    # native linux-x86_64 path is unchanged (ISSUE-0008 regression-safe).
    case "${TARGET_TRIPLE}" in
        *-linux-*)
            strip --strip-all "${BUILD_DIR}/mnemosyne" || strip --strip-debug "${BUILD_DIR}/mnemosyne" || log "warning: strip failed (non-fatal)"
            # Strip lib/**/*.so as well — these ship unstripped from PyOxidizer.
            local so_count=0 strip_fail=0
            while IFS= read -r -d '' so; do
                so_count=$((so_count + 1))
                if ! strip --strip-all "${so}" 2>/dev/null && ! strip --strip-debug "${so}" 2>/dev/null; then
                    strip_fail=$((strip_fail + 1))
                fi
            done < <(find "${BUILD_DIR}/lib" -type f -name '*.so' -print0 2>/dev/null)
            log "stripped ${so_count} .so files in lib/ (${strip_fail} failed)"
            binary_bytes="$(stat -c %s "${BUILD_DIR}/mnemosyne")"
            lib_bytes="$(du -sb "${BUILD_DIR}/lib" 2>/dev/null | cut -f1)"
            companion_bytes=0
            for pkg in jsonschema_specifications referencing; do
                [[ -d "${BUILD_DIR}/${pkg}" ]] && companion_bytes=$((companion_bytes + $(du -sb "${BUILD_DIR}/${pkg}" | cut -f1)))
            done
            ;;
        *-apple-darwin)
            strip -x "${BUILD_DIR}/mnemosyne" || log "warning: strip failed (non-fatal)"
            # macOS stat: -f %z for size in bytes; du -sk for KB.
            binary_bytes="$(stat -f %z "${BUILD_DIR}/mnemosyne")"
            lib_bytes="$(du -sk "${BUILD_DIR}/lib" 2>/dev/null | awk '{print $1*1024}')"
            companion_bytes=0
            for pkg in jsonschema_specifications referencing; do
                if [[ -d "${BUILD_DIR}/${pkg}" ]]; then
                    companion_bytes=$((companion_bytes + $(du -sk "${BUILD_DIR}/${pkg}" | awk '{print $1*1024}')))
                fi
            done
            ;;
        *-windows-*)
            # Windows: skip strip (PE), use wc -c for byte count, lib is .pyd/.exe.
            binary_bytes="$(wc -c < "${BUILD_DIR}/mnemosyne" | tr -d ' ')"
            lib_bytes="$(du -sk "${BUILD_DIR}/lib" 2>/dev/null | awk '{print $1*1024}')"
            companion_bytes=0
            for pkg in jsonschema_specifications referencing; do
                if [[ -d "${BUILD_DIR}/${pkg}" ]]; then
                    companion_bytes=$((companion_bytes + $(du -sk "${BUILD_DIR}/${pkg}" | awk '{print $1*1024}')))
                fi
            done
            ;;
        *)
            err "unsupported TARGET_TRIPLE: ${TARGET_TRIPLE}"
            return 1
            ;;
    esac
    binary_mb="$(awk -v b="${binary_bytes}" 'BEGIN{printf "%.1f", b/1024/1024}')"
    # Full distribution footprint: binary + lib/ + filesystem-shipped companion
    # dirs (jsonschema_specifications, referencing). PyOxidizer 0.24 cannot
    # collapse these into the binary proper — the path forward is ISSUE-0009.
    local dist_bytes dist_mb
    dist_bytes=$((binary_bytes + lib_bytes + companion_bytes))
    dist_mb="$(awk -v b="${dist_bytes}" 'BEGIN{printf "%.1f", b/1024/1024}')"
    log "binary ready: ${BUILD_DIR}/mnemosyne (${binary_mb} MB, ${binary_bytes} bytes)"
    log "distribution footprint: ${dist_mb} MB (binary ${binary_mb} MB + lib $(awk -v b="${lib_bytes}" 'BEGIN{printf "%.1f", b/1024/1024}') MB + companion $(awk -v b="${companion_bytes}" 'BEGIN{printf "%.1f", b/1024/1024}') MB)"
    # AC6 reclassified advisory (PM Amendment in ISSUE-0008): the full
    # distribution footprint on PyOxidizer 0.24 + CPython 3.10 + the required
    # runtime dep set (cryptography alone is ~11MB stripped in lib/) is over
    # the 100MB budget. The path to <=100MB is the PyOxidizer 0.4x upgrade
    # (ISSUE-0009). We log the measurement rather than failing the build.
    if (( dist_bytes > 100 * 1024 * 1024 )); then
        log "NOTE: AC6 advisory — distribution is ${dist_mb} MB (over 100 MB; owned by ISSUE-0009 PyOxidizer 0.4x upgrade; see BINARY_BUILD.md)"
    fi
}

main() {
    case "${1:-build}" in
        --check)
            check_toolchain
            ;;
        --debug)
            BUILD_MODE="debug"
            check_toolchain
            build_rust_extension
            build_dependency_venv
            bake_version
            bake_skill
            run_pyoxidizer
            install_binary
            ;;
        build|"")
            check_toolchain
            build_rust_extension
            build_dependency_venv
            bake_version
            bake_skill
            run_pyoxidizer
            install_binary
            ;;
        *)
            err "unknown argument: $1 (expected: --check | build | --debug)"
            exit 2
            ;;
    esac
}

main "$@"

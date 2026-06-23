#!/usr/bin/env bash
# Build the mnemosyne single-binary distribution via PyOxidizer.
#
# Target: linux-x86_64 only (ISSUE-0008 / SPEC-PACKAGE-001 T5).
# Cross-platform matrix, install.sh, and CI are ISSUE-0009 (PACKAGE-D).
#
# Pipeline (T1 POC + T5 base binary, REQ-PKG-001):
#   1. Verify toolchain (pyoxidizer, cargo/rustc, maturin).
#   2. Build mnemosyne-core Rust extension via maturin (produces the .so that
#      pyoxidizer.bzl embeds as PythonExtensionModule — R-PKG-001 de-risk).
#   3. `pyoxidizer build --target-triple x86_64-unknown-linux-gnu`.
#   4. Copy the stripped binary to build/mnemosyne.
#   5. Print size (AC6).
#
# Usage:
#   scripts/build_binary.sh            # build + copy + size report
#   scripts/build_binary.sh --check    # only verify toolchain availability
#
# Environment:
#   PYOXIDIZER_VERSION  (default: 0.24.0; see pin comment in pyoxidizer.bzl)
#   PYTHON_VERSION      (default: 3.12; pin comment in pyoxidizer.bzl)
set -euo pipefail

PYOXIDIZER_VERSION="${PYOXIDIZER_VERSION:-0.24.0}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build"
RUST_EXT_DIR="${REPO_ROOT}/mnemosyne-core/target/wheels"

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
    if [[ "$missing" -ne 0 ]]; then
        cat >&2 <<EOF

To install the toolchain (outside ISSUE-0008 scope — recorded for repro):

  # Rust + maturin (PyO3 build of mnemosyne-core)
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source "\$HOME/.cargo/env"
  pip install maturin

  # PyOxidizer (pin: see pyoxidizer.bzl header)
  pip install pyoxidizer==${PYOXIDIZER_VERSION}

Re-run this script after the toolchain is on PATH.
EOF
        return 1
    fi
    log "toolchain OK (pyoxidizer $(pyoxidizer --version 2>&1 | head -1))"
    return 0
}

build_rust_extension() {
    log "building mnemosyne-core via maturin (target: cpython-${PYTHON_VERSION}-x86_64-linux-gnu)"
    mkdir -p "${RUST_EXT_DIR}"
    # Produce the extension module .so. `--interpreter` constrains to the
    # embedded CPython version; `--strip` reduces binary size.
    (cd "${REPO_ROOT}/mnemosyne-core" && \
        maturin build --release --interpreter "python${PYTHON_VERSION}" --strip)
    # Copy the produced .so to the location referenced by pyoxidizer.bzl.
    local so_path
    so_path="$(find "${REPO_ROOT}/mnemosyne-core/target/wheels" -name 'mnemosyne_core*.so' | head -1 || true)"
    if [[ -z "${so_path}" ]]; then
        err "maturin did not produce mnemosyne_core*.so under mnemosyne-core/target/wheels"
        return 1
    fi
    cp -f "${so_path}" "${RUST_EXT_DIR}/mnemosyne_core.so"
    log "rust extension ready: ${RUST_EXT_DIR}/mnemosyne_core.so"
}

run_pyoxidizer() {
    log "pyoxidizer build (target: x86_64-unknown-linux-gnu)"
    (cd "${REPO_ROOT}" && \
        pyoxidizer build --target-triple x86_64-unknown-linux-gnu)
}

install_binary() {
    local src
    src="${REPO_ROOT}/build/x86_64-unknown-linux-gnu/release/install/mnemosyne"
    if [[ ! -f "${src}" ]]; then
        err "pyoxidizer did not produce ${src}"
        return 1
    fi
    mkdir -p "${BUILD_DIR}"
    cp -f "${src}" "${BUILD_DIR}/mnemosyne"
    strip --strip-debug "${BUILD_DIR}/mnemosyne" || log "warning: strip failed (non-fatal)"
    local size_bytes size_mb
    size_bytes="$(stat -c %s "${BUILD_DIR}/mnemosyne")"
    size_mb="$(awk -v b="${size_bytes}" 'BEGIN{printf "%.1f", b/1024/1024}')"
    log "binary ready: ${BUILD_DIR}/mnemosyne (${size_mb} MB, ${size_bytes} bytes)"
    if (( size_bytes > 100 * 1024 * 1024 )); then
        err "AC6 FAIL: binary exceeds 100 MB (R-PKG-006); apply stdlib trimming"
        return 1
    fi
}

main() {
    case "${1:-build}" in
        --check)
            check_toolchain
            ;;
        build|"")
            check_toolchain
            build_rust_extension
            run_pyoxidizer
            install_binary
            ;;
        *)
            err "unknown argument: $1 (expected: --check | build)"
            exit 2
            ;;
    esac
}

main "$@"

#!/bin/sh
# install.sh — fetch + verify + install the mnemosyne single binary.
#
# SPEC: SPEC-PACKAGE-001 (PACKAGE-D, REQ-PKG-009)
# Issue: ISSUE-0009
#
# Usage:
#   curl -fsSL https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.sh | sh
#   curl -fsSL .../install.sh | MNEMOSYNE_INSTALL_DIR=$HOME/bin sh
#   curl -fsSL .../install.sh | sh -s -- --force
#
# Behavior:
#   1. Detect OS (uname -s) + arch (uname -m).
#   2. Map to a release-asset tag: linux-x86_64, linux-aarch64,
#      darwin-arm64, darwin-x86_64. (windows is handled by install.ps1.)
#   3. Fetch mnemosyne-<tag> + SHA256SUMS.txt from the latest GitHub Release.
#   4. Verify sha256; abort on mismatch (non-zero exit).
#   5. Install to ${MNEMOSYNE_INSTALL_DIR:-/usr/local/bin}/mnemosyne
#      (chmod +x). Refuse overwrite unless --force / MNEMOSYNE_FORCE=1.
#   6. On darwin, print the unsigned-binary xattr workaround (R-PKG-005).
set -eu

REPO="tipsy-kereru/mnemosyne"
BASE_URL="https://github.com/${REPO}/releases/latest/download"
INSTALL_DIR="${MNEMOSYNE_INSTALL_DIR:-/usr/local/bin}"
FORCE="${MNEMOSYNE_FORCE:-0}"

err() { printf 'install.sh: ERROR: %s\n' "$*" >&2; }
log() { printf 'install.sh: %s\n' "$*"; }

# Parse args (only --force is supported).
for arg in "$@"; do
    case "$arg" in
        --force|-f) FORCE=1 ;;
        -h|--help)
            cat <<EOF
Usage: install.sh [--force]
  --force         Overwrite an existing mnemosyne binary.
Environment:
  MNEMOSYNE_INSTALL_DIR  Install directory (default: /usr/local/bin)
  MNEMOSYNE_FORCE=1      Same as --force.
EOF
            exit 0
            ;;
        *) err "unknown argument: $arg (use --help)"; exit 2 ;;
    esac
done

# ---- platform detection -----------------------------------------------------
detect_platform() {
    os="$(uname -s)"
    arch="$(uname -m)"
    case "${os}" in
        Linux)
            case "${arch}" in
                x86_64|amd64) printf 'linux-x86_64' ;;
                aarch64|arm64) printf 'linux-aarch64' ;;
                *) err "unsupported linux arch: ${arch}"; return 1 ;;
            esac
            ;;
        Darwin)
            case "${arch}" in
                arm64) printf 'darwin-arm64' ;;
                x86_64) printf 'darwin-x86_64' ;;
                *) err "unsupported darwin arch: ${arch}"; return 1 ;;
            esac
            ;;
        MINGW*|MSYS*|CYGWIN*)
            err "windows detected; use install.ps1 instead"
            return 1
            ;;
        *) err "unsupported OS: ${os}"; return 1 ;;
    esac
}

# Resolve the sha256-hashing command (BSD shasum vs coreutils sha256sum).
hash_cmd() {
    if command -v shasum >/dev/null 2>&1; then
        printf 'shasum -a 256'
    elif command -v sha256sum >/dev/null 2>&1; then
        printf 'sha256sum'
    else
        err "neither shasum nor sha256sum is available"
        return 1
    fi
}

fetch() {
    # $1 = url, $2 = output path. curl preferred, wget fallback.
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$2" "$1"
    else
        err "neither curl nor wget is available"
        return 1
    fi
}

main() {
    platform="$(detect_platform)" || exit 1
    asset="mnemosyne-${platform}"
    bin_path="${INSTALL_DIR}/mnemosyne"

    log "detected platform: ${platform}"
    log "install dir: ${INSTALL_DIR}"

    if [ -e "${bin_path}" ] && [ "${FORCE}" != "1" ]; then
        err "refusing to overwrite existing ${bin_path} (pass --force or MNEMOSYNE_FORCE=1)"
        exit 1
    fi

    tmpdir="$(mktemp -d 2>/dev/null || mktemp -d -t mnemosyne)"
    trap 'rm -rf "${tmpdir}"' EXIT
    bin_tmp="${tmpdir}/${asset}"
    sums_tmp="${tmpdir}/SHA256SUMS.txt"

    log "fetching ${asset} + SHA256SUMS.txt"
    fetch "${BASE_URL}/${asset}" "${bin_tmp}" || { err "download failed for ${asset}"; exit 1; }
    fetch "${BASE_URL}/SHA256SUMS.txt" "${sums_tmp}" || { err "download failed for SHA256SUMS.txt"; exit 1; }

    # Extract the expected hash for this asset from SHA256SUMS.txt.
    expected="$(grep " ${asset}\$" "${sums_tmp}" | awk '{print $1}' | head -1)"
    if [ -z "${expected}" ]; then
        err "no checksum entry for ${asset} in SHA256SUMS.txt"
        exit 1
    fi

    hasher="$(hash_cmd)" || exit 1
    # shellcheck disable=SC2086
    actual="$(eval "${hasher}" "${bin_tmp}" | awk '{print $1}')"
    if [ "${actual}" != "${expected}" ]; then
        err "checksum mismatch for ${asset}"
        err "  expected: ${expected}"
        err "  actual:   ${actual}"
        exit 1
    fi
    log "checksum OK (${expected})"

    if [ ! -d "${INSTALL_DIR}" ]; then
        mkdir -p "${INSTALL_DIR}" 2>/dev/null || {
            err "cannot create ${INSTALL_DIR} (try sudo or set MNEMOSYNE_INSTALL_DIR)"
            exit 1
        }
    fi

    if [ ! -w "${INSTALL_DIR}" ]; then
        err "${INSTALL_DIR} is not writable (retry with sudo, or set MNEMOSYNE_INSTALL_DIR=\$HOME/bin)"
        exit 1
    fi

    mv "${bin_tmp}" "${bin_path}"
    chmod +x "${bin_path}"
    log "installed: ${bin_path}"

    case "${platform}" in
        darwin-*)
            cat <<EOF

NOTE: macOS binaries are NOT notarized (R-PKG-005). On first run, Gatekeeper
may block the binary. If so, run:

  xattr -d com.apple.quarantine "${bin_path}"

EOF
            ;;
    esac

    log "next steps:"
    log "  ${bin_path} --help"
    log "  ${bin_path} extension install slm   # add the SLM payload"
}

main "$@"

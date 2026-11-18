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
#   MNEMOSYNE_FORCE=1 curl -fsSL .../install.sh | sh
#
# NOTE: '--force' / '--dir' are flags for THIS script, not for curl. With the
# pipe form they must reach sh, so use 'sh -s -- --force' or the MNEMOSYNE_*
# env vars. 'curl ... --force | sh' does NOT pass --force to the installer.
#
# Behavior:
#   1. Detect OS (uname -s) + arch (uname -m).
#   2. Map to a release-asset tag: linux-x86_64, linux-aarch64,
#      darwin-arm64, darwin-x86_64. (windows is handled by install.ps1.)
#   3. Fetch mnemosyne-<tag>, mnemosyne-<tag>.dist.tar.gz + SHA256SUMS.txt
#      from the latest GitHub Release.
#   4. Verify sha256 of both downloads; abort on mismatch (non-zero exit).
#   5. Install to ${MNEMOSYNE_INSTALL_DIR:-$HOME/.local/bin}/mnemosyne
#      (chmod +x) and unpack the companion directories from the tarball
#      (lib/, anyio/, referencing/, jsonschema_specifications/) next to it.
#      The binary cannot run 'mcp serve' without them. Refuse overwrite of
#      the binary or any companion directory unless --force / MNEMOSYNE_FORCE=1.
#   6. On darwin, print the unsigned-binary xattr workaround (R-PKG-005).
set -eu

REPO="tipsy-kereru/mnemosyne"
BASE_URL="https://github.com/${REPO}/releases/latest/download"
INSTALL_DIR="${MNEMOSYNE_INSTALL_DIR:-$HOME/.local/bin}"
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
  --force         Overwrite an existing mnemosyne binary and companion directories.
Environment:
  MNEMOSYNE_INSTALL_DIR  Install directory (default: \$HOME/.local/bin)
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
            # Under Rosetta (translated shell) uname -m reports x86_64 even on
            # Apple Silicon. Probe the hardware directly: hw.optional.arm64=1
            # means the physical CPU is arm64, so prefer the darwin-arm64
            # binary regardless of what the translated shell reports. (We do
            # NOT rely on sysctl_proc_translated — it is not populated on every
            # macOS release / shell type.)
            if [ "${arch}" = "x86_64" ] && [ "$(sysctl -n hw.optional.arm64 2>/dev/null || printf 0)" = "1" ]; then
                arch="arm64"
            fi
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

# Verify file $1 against its entry named $2 in the SHA256SUMS.txt at $3.
verify_asset() {
    file="$1"
    name="$2"
    sums="$3"
    # Tolerate the leading "./" that GNU sha256sum emits when fed "./name"
    # paths (the release workflow's find produces these); match a space or a
    # slash immediately before the asset name.
    expected="$(grep "[ /]${name}\$" "${sums}" | awk '{print $1}' | head -1)"
    if [ -z "${expected}" ]; then
        err "no checksum entry for ${name} in SHA256SUMS.txt"
        return 1
    fi
    hasher="$(hash_cmd)" || return 1
    # shellcheck disable=SC2086
    actual="$(eval "${hasher}" "${file}" | awk '{print $1}')"
    if [ "${actual}" != "${expected}" ]; then
        err "checksum mismatch for ${name}"
        err "  expected: ${expected}"
        err "  actual:   ${actual}"
        return 1
    fi
    log "checksum OK (${name}: ${expected})"
}

# Print the top-level entry names of the companion tarball $1, one per line.
# Rejects archives that could write outside INSTALL_DIR or use unusual names.
companion_names() {
    entries="$(tar -tzf "$1")" || { err "cannot read ${1##*/}"; return 1; }
    if printf '%s\n' "${entries}" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
        err "unsafe path in ${1##*/}"
        return 1
    fi
    names="$(printf '%s\n' "${entries}" | cut -d/ -f1 | sort -u)"
    if printf '%s\n' "${names}" | grep -Evq '^[A-Za-z0-9_][A-Za-z0-9._-]*$'; then
        err "unexpected entry name in ${1##*/}"
        return 1
    fi
    printf '%s\n' "${names}"
}

main() {
    platform="$(detect_platform)" || exit 1
    asset="mnemosyne-${platform}"
    dist_asset="${asset}.dist.tar.gz"
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
    dist_tmp="${tmpdir}/${dist_asset}"
    sums_tmp="${tmpdir}/SHA256SUMS.txt"

    log "fetching ${asset}, ${dist_asset} + SHA256SUMS.txt"
    fetch "${BASE_URL}/${asset}" "${bin_tmp}" || { err "download failed for ${asset}"; exit 1; }
    fetch "${BASE_URL}/${dist_asset}" "${dist_tmp}" || { err "download failed for ${dist_asset}"; exit 1; }
    fetch "${BASE_URL}/SHA256SUMS.txt" "${sums_tmp}" || { err "download failed for SHA256SUMS.txt"; exit 1; }

    verify_asset "${bin_tmp}" "${asset}" "${sums_tmp}" || exit 1
    verify_asset "${dist_tmp}" "${dist_asset}" "${sums_tmp}" || exit 1
    names="$(companion_names "${dist_tmp}")" || exit 1

    if [ "${FORCE}" != "1" ]; then
        for name in ${names}; do
            if [ -e "${INSTALL_DIR}/${name}" ]; then
                err "refusing to overwrite existing ${INSTALL_DIR}/${name} (pass --force or MNEMOSYNE_FORCE=1)"
                exit 1
            fi
        done
    fi

    if [ ! -d "${INSTALL_DIR}" ]; then
        mkdir -p "${INSTALL_DIR}" 2>/dev/null || {
            err "cannot create ${INSTALL_DIR} (try sudo or set MNEMOSYNE_INSTALL_DIR)"
            exit 1
        }
    fi

    if [ ! -w "${INSTALL_DIR}" ]; then
        err "${INSTALL_DIR} is not writable (ensure it exists and is writable, or set MNEMOSYNE_INSTALL_DIR)"
        exit 1
    fi

    # Companions first: a failed unpack must not leave a binary that boots
    # but cannot serve MCP.
    tar -xzf "${dist_tmp}" -C "${INSTALL_DIR}" || { err "failed to unpack ${dist_asset}"; exit 1; }
    mv "${bin_tmp}" "${bin_path}"
    chmod +x "${bin_path}"
    log "installed: ${bin_path}"
    log "companions: $(printf '%s' "${names}" | tr '\n' ' ')(in ${INSTALL_DIR})"

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
    log "  ${bin_path} ingest add . --domain coding   # seed graph + wiki"
}

main "$@"

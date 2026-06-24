#!/usr/bin/env bash
# Build recipe for the `pdf` extension payload (ISSUE-0007 / SPEC-PACKAGE-001).
#
# Assembles pymupdf (fitz) into a payload directory, computes per-file
# SHA256, and emits the canonical manifest.json. The output is a
# platform/python-tagged tarball + manifest suitable for attaching to a
# GitHub Release on tipsy-kereru/mnemosyne-ext-pdf.
#
# NO wheels are committed to the repo. This script fetches them from PyPI
# into a clean virtualenv at build time.
#
# Usage:
#   MNEMOSYNE_EXT_VERSION=1.0.0 ./build.sh
#
# Output:
#   dist/pdf-<version>-<platform>-<python_tag>.tar.gz
#   dist/manifest.json
set -euo pipefail

name="pdf"
version="${MNEMOSYNE_EXT_VERSION:-1.0.0}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work_dir="$(mktemp -d)"
payload_dir="${work_dir}/payload"
dist_dir="${script_dir}/dist"

mkdir -p "${payload_dir}" "${dist_dir}"

detect_platform() {
    local os machine
    os="$(uname -s | tr '[:upper:]' '[:lower:]')"
    machine="$(uname -m)"
    case "${machine}" in
        x86_64|amd64) arch="x86_64" ;;
        arm64|aarch64) arch="arm64" ;;
        *) arch="${machine}" ;;
    esac
    echo "${os}-${arch}"
}
detect_python_tag() {
    python -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')"
}

platform="${MNEMOSYNE_EXT_PLATFORM:-$(detect_platform)}"
python_tag="$(detect_python_tag)"

echo "==> Building ${name} ${version} for ${platform}/${python_tag}"

# Stage 1: isolated venv with pymupdf only.
python -m venv "${work_dir}/venv"
# shellcheck disable=SC1091
source "${work_dir}/venv/bin/activate"
pip install --upgrade pip --quiet
pip install --quiet pymupdf

# Stage 2: copy importable packages into payload.
site_pkg="$(python -c 'import site; print(site.getsitepackages()[0])')"
for pkg in fitz pymupdf; do
    if [ -d "${site_pkg}/${pkg}" ]; then
        cp -r "${site_pkg}/${pkg}" "${payload_dir}/"
    fi
done

# Stage 3: compute per-file SHA256 and emit manifest.json.
echo "==> Computing SHA256 digests"
sha_map_file="${work_dir}/sha.json"
python - "${payload_dir}" "${name}" "${version}" "${platform}" "${python_tag}" > "${sha_map_file}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

payload_dir = Path(sys.argv[1])
name, version, platform, python_tag = sys.argv[2:6]
sha = {}
for entry in sorted(payload_dir.rglob("*")):
    if entry.is_file():
        rel = entry.relative_to(payload_dir).as_posix()
        h = hashlib.sha256()
        with entry.open("rb") as fh:
            for block in iter(lambda: fh.read(65536), b""):
                h.update(block)
        sha[rel] = h.hexdigest()
manifest = {
    "name": name,
    "version": version,
    "platform": platform,
    "python_tag": python_tag,
    "sha256": sha,
    "enables": ["fitz"],
    "signer": "tipsy-kereru",
}
print(json.dumps(manifest, indent=2, sort_keys=True))
PY

# Stage 4: tar up the payload.
tarball="${dist_dir}/${name}-${version}-${platform}-${python_tag}.tar.gz"
echo "==> Packing ${tarball}"
tar -czf "${tarball}" -C "${payload_dir}" .
cp "${sha_map_file}" "${dist_dir}/manifest.json"

echo "==> Done"
echo "    tarball: ${tarball}"
echo "    manifest: ${dist_dir}/manifest.json"
echo "    files: $(python -c 'import json; print(len(json.load(open("'"${dist_dir}"'/manifest.json"))["sha256"]))')"

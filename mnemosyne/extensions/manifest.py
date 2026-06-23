"""Extension manifest schema + SHA256 integrity verification (REQ-PKG-010).

A manifest is a JSON document that ships beside an extension payload. It
binds the payload to a name/version/platform/python_tag and enumerates the
SHA256 of every file in the payload. The installer refuses to proceed on
any mismatch and rolls back so no partial install is left on disk.

Schema (manifest.json)::

    {
      "name": "slm",
      "version": "1.0.0",
      "platform": "linux-x86_64",
      "python_tag": "cp312",
      "sha256": {
        "gliner/__init__.py": "<hex>",
        ...
      },
      "enables": ["gliner", "torch"],
      "signer": "tipsy-kereru",
      "signature": "<optional detached sig; not verified by base install>"
    }

The ``signature`` field is optional and not cryptographically verified by
the base installer in this revision (cosign/notarization land in
PACKAGE-D). ``signer`` is recorded for audit. SHA256-per-file is the load-
bearing integrity guarantee.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Extensions live under a bounded directory; manifests must not reference
# paths that escape it (no absolute paths, no ``..`` traversal). This regex
# bounds the relative-path shape we accept in ``sha256`` keys.
_SAFE_RELPATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*\.[A-Za-z0-9]+$")


class ManifestError(ValueError):
    """Raised when a manifest is malformed, missing, or tampered."""


@dataclass(frozen=True)
class ExtensionManifest:
    """Typed view over an extension's ``manifest.json``."""

    name: str
    version: str
    platform: str
    python_tag: str
    sha256: dict[str, str] = field(default_factory=dict)
    enables: tuple[str, ...] = ()
    signer: str = ""
    signature: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtensionManifest":
        if not isinstance(data, dict):
            raise ManifestError("manifest root must be a JSON object")
        try:
            name = data["name"]
            version = data["version"]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ManifestError(f"manifest missing required key: {exc}") from exc
        if not isinstance(name, str) or not name:
            raise ManifestError("manifest 'name' must be a non-empty string")
        if not isinstance(version, str) or not version:
            raise ManifestError("manifest 'version' must be a non-empty string")
        platform = data.get("platform", "any")
        python_tag = data.get("python_tag", "cp312")
        sha_map = data.get("sha256", {})
        if not isinstance(sha_map, dict):
            raise ManifestError("manifest 'sha256' must be an object")
        for relpath, digest in sha_map.items():
            if not isinstance(relpath, str) or not _SAFE_RELPATH.match(relpath):
                raise ManifestError(
                    f"manifest 'sha256' key is not a safe relative path: {relpath!r}"
                )
            # Path traversal hardening: reject any component that escapes.
            parts = Path(relpath).parts
            if ".." in parts or Path(relpath).is_absolute():
                raise ManifestError(
                    f"manifest 'sha256' key escapes payload dir: {relpath!r}"
                )
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ManifestError(
                    f"manifest 'sha256[{relpath}]' must be a 64-hex SHA256 digest"
                )
        enables = tuple(data.get("enables", []) or ())
        return cls(
            name=name,
            version=version,
            platform=str(platform),
            python_tag=str(python_tag),
            sha256=dict(sha_map),
            enables=enables,
            signer=str(data.get("signer", "")),
            signature=str(data.get("signature", "")),
        )

    @classmethod
    def from_path(cls, path: Path) -> "ExtensionManifest":
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise ManifestError(f"cannot read manifest at {path}: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "platform": self.platform,
            "python_tag": self.python_tag,
            "sha256": dict(self.sha256),
            "enables": list(self.enables),
            "signer": self.signer,
            "signature": self.signature,
        }


def sha256_file(path: Path, *, chunk: int = 65536) -> str:
    """Compute the SHA256 hex digest of ``path`` streaming in chunks."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def verify_payload(manifest: ExtensionManifest, payload_dir: Path) -> None:
    """Verify every file listed in the manifest exists with matching SHA256.

    Raises :class:`ManifestError` on any mismatch (missing file, extra file,
    digest mismatch). Callers must perform rollback on raise to avoid leaving
    a partial install on disk.
    """
    payload_dir = Path(payload_dir)
    if not payload_dir.is_dir():
        raise ManifestError(f"payload dir does not exist: {payload_dir}")

    seen: set[Path] = set()
    for relpath, expected in manifest.sha256.items():
        # Defensive: from_dict already rejected traversal, but re-check at
        # verify time in case the manifest was constructed bypassing parsing.
        target = (payload_dir / relpath).resolve()
        try:
            target.relative_to(payload_dir.resolve())
        except ValueError as exc:
            raise ManifestError(
                f"manifest path escapes payload dir: {relpath!r}"
            ) from exc
        if not target.is_file():
            raise ManifestError(f"manifest lists missing file: {relpath}")
        actual = sha256_file(target)
        if actual != expected:
            raise ManifestError(
                f"SHA256 mismatch for {relpath}: expected {expected}, got {actual}"
            )
        seen.add(target)

    # Reject undeclared files -- an attacker appending a malicious payload
    # file would otherwise survive install undetected.
    for entry in payload_dir.rglob("*"):
        if entry.is_file() and entry.resolve() not in seen:
            # The manifest itself is the one expected non-payload file; it
            # lives at the payload root and is not in the sha256 map.
            if entry.name == "manifest.json" and entry.parent == payload_dir:
                continue
            raise ManifestError(
                f"undeclared file in payload: {entry.relative_to(payload_dir)}"
            )

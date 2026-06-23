"""Extension installer + manager (REQ-PKG-003 / REQ-PKG-004 / REQ-PKG-010).

This module is the single entry point for all ``mnemosyne extension`` verbs.
It owns:

  - resolving the extensions home directory (``MNEMOSYNE_HOME``-aware).
  - downloading a release payload from a :class:`~mnemosyne.extensions.registry.Registry`.
  - verifying every file's SHA256 against the signed manifest and rolling
    back atomically on any mismatch (no partial install left on disk).
  - listing installed extensions and their versions.
  - removing extensions and recording tombstones for audit.
  - upgrade / search / info.

The installer never ``exec``/``eval``s downloaded code. Activation is by
sys.path injection of the payload directory -- see
:mod:`mnemosyne.extensions.loader`.
"""

from __future__ import annotations

import json
import platform
import shutil
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from mnemosyne.extensions.manifest import (
    ExtensionManifest,
    ManifestError,
    sha256_file,
    verify_payload,
)
from mnemosyne.extensions.registry import (
    HttpGithubRegistry,
    Release,
    ReleaseAsset,
    Registry,
    RegistryError,
)

# Tombstone record appended to extensions/.removed.jsonl on ``remove``.
# Filesystem deletion is destructive; we keep an audit trail instead of a
# silent disappearance.
_REMOVED_LOG_NAME = ".removed.jsonl"


class IntegrityError(RuntimeError):
    """Raised when a payload fails SHA256 or manifest verification."""


class ExtensionNotFoundError(RuntimeError):
    """Raised when an extension is not installed (list/remove/info)."""


def _detect_platform() -> str:
    """Return a platform tag matching release asset naming (e.g. linux-x86_64)."""
    os_name = platform.system().lower()
    machine = platform.machine().lower()
    if os_name == "linux":
        plat = "linux"
    elif os_name == "darwin":
        plat = "darwin"
    elif os_name == "windows":
        plat = "windows"
    else:  # pragma: no cover - unusual platforms
        plat = os_name
    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:  # pragma: no cover
        arch = machine
    return f"{plat}-{arch}"


def _detect_python_tag() -> str:
    impl = platform.python_implementation()
    if impl == "CPython":
        return f"cp{sys.version_info.major}{sys.version_info.minor}"
    return impl.lower()  # pragma: no cover


@dataclass(frozen=True)
class InstalledExtension:
    """An installed extension as reported by ``list``/``info``."""

    name: str
    version: str
    path: Path
    manifest: ExtensionManifest

    @property
    def size_bytes(self) -> int:
        total = 0
        for p in self.path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        return total


class ExtensionManager:
    """Owns the extensions home directory and all install/remove/list verbs."""

    def __init__(
        self,
        home: Optional[Path] = None,
        *,
        registry: Optional[Registry] = None,
        platform_tag: Optional[str] = None,
        python_tag: Optional[str] = None,
    ) -> None:
        # Extensions home: $MNEMOSYNE_HOME/extensions (default ~/.mnemosyne).
        env_home = home
        if env_home is None:
            import os

            base = os.environ.get("MNEMOSYNE_HOME")
            if base:
                env_home = Path(base)
            else:
                env_home = Path.home() / ".mnemosyne"
        self.home: Path = Path(env_home)
        self.extensions_dir: Path = self.home / "extensions"
        self.registry: Registry = registry if registry is not None else HttpGithubRegistry()
        self.platform_tag = platform_tag or _detect_platform()
        self.python_tag = python_tag or _detect_python_tag()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def payload_dir(self, name: str, version: str) -> Path:
        return self.extensions_dir / name / version

    def installed_versions(self, name: str) -> list[Path]:
        base = self.extensions_dir / name
        if not base.is_dir():
            return []
        return sorted(
            (d for d in base.iterdir() if d.is_dir() and (d / "manifest.json").exists()),
            key=lambda p: p.name,
        )

    def latest_installed_version(self, name: str) -> Optional[InstalledExtension]:
        versions = self.installed_versions(name)
        if not versions:
            return None
        # Highest semver wins (REQ-PKG-003). Sort by parsed semver tuple.
        def key(inst: Path) -> tuple[int, ...]:
            return _parse_semver(inst.name)

        latest = max(versions, key=key)
        return InstalledExtension(
            name=name,
            version=latest.name,
            path=latest,
            manifest=ExtensionManifest.from_path(latest / "manifest.json"),
        )

    # ------------------------------------------------------------------
    # install
    # ------------------------------------------------------------------

    def install(
        self,
        name: str,
        *,
        version: Optional[str] = None,
        force: bool = False,
    ) -> InstalledExtension:
        """Download, verify, and install ``name`` at ``version`` (or latest).

        Atomicity: extract into a temp sibling dir, verify, then rename into
        place. On any :class:`IntegrityError` or :class:`ManifestError` we
        remove the temp dir so no partial install survives.
        """
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise IntegrityError(f"invalid extension name: {name!r}")

        release = (
            self.registry.release(name, version)
            if version
            else self.registry.latest_release(name)
        )
        try:
            manifest = ExtensionManifest.from_dict(json.loads(release.manifest_json))
        except (json.JSONDecodeError, ManifestError) as exc:
            # Tamper guard (REQ-PKG-010): a corrupt or malformed manifest
            # from the registry is an integrity failure, not a crash.
            raise IntegrityError(f"manifest is not valid JSON: {exc}") from exc
        if manifest.name != name:
            raise IntegrityError(
                f"manifest name {manifest.name!r} does not match requested {name!r}"
            )

        # Downgrade protection: refuse to install an older version over a
        # newer one unless --force. Without this an attacker who controls the
        # registry could pin a user to a vulnerable old release.
        existing = self.latest_installed_version(name)
        if existing is not None and not force:
            if _parse_semver(manifest.version) < _parse_semver(existing.version):
                raise IntegrityError(
                    f"refusing downgrade: installed {existing.version} > requested "
                    f"{manifest.version} (use --force to override)"
                )

        target = self.payload_dir(name, manifest.version)
        name_dir = self.extensions_dir / name
        if target.exists():
            if not force:
                raise IntegrityError(
                    f"{name} {manifest.version} already installed (use --force to reinstall)"
                )
            shutil.rmtree(target)
        # Record whether the per-name parent dir pre-existed so rollback can
        # clean up an empty skeleton it created (REQ-PKG-010: no partial
        # install left on disk, not even an empty name directory).
        name_dir_existed_before = name_dir.is_dir()

        # Staging dir beside target so the rename is atomic on the same
        # filesystem.
        staging = target.with_name(f"{target.name}.staging")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)

        try:
            payload_asset = self._select_payload_asset(release, name, manifest.version)
            archive_path = staging / payload_asset.name
            self.registry.fetch_asset(payload_asset, archive_path)

            # Extract archive into staging root (manifest.json lands at root).
            _safe_extract_tarball(archive_path, staging)
            archive_path.unlink(missing_ok=True)

            # Persist the canonical manifest (authoritative, from the
            # release -- not whatever was inside the tarball).
            (staging / "manifest.json").write_text(
                json.dumps(manifest.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )

            # Verify every file in the payload against the manifest.
            verify_payload(manifest, staging)

            # Atomic-ish swap into place.
            staging.replace(target)
        except (IntegrityError, ManifestError) as exc:
            shutil.rmtree(staging, ignore_errors=True)
            self._cleanup_empty_skeleton(name_dir, name_dir_existed_before)
            raise IntegrityError(f"install aborted: {exc}") from exc
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            self._cleanup_empty_skeleton(name_dir, name_dir_existed_before)
            raise

        return InstalledExtension(
            name=name,
            version=manifest.version,
            path=target,
            manifest=manifest,
        )

    def _cleanup_empty_skeleton(self, name_dir: Path, existed_before: bool) -> None:
        """Remove an empty per-name dir created during a failed install.

        REQ-PKG-010: no partial install left on disk. ``install`` creates
        ``extensions/<name>/`` (via ``parents=True`` on the staging mkdir)
        before verification; if the install aborts and that dir is empty and
        did not pre-exist (no other version installed), remove it so a failed
        install leaves no trace.
        """
        if existed_before:
            return
        try:
            if name_dir.is_dir() and not any(name_dir.iterdir()):
                name_dir.rmdir()
        except OSError:
            # Best-effort cleanup; a non-empty dir (concurrent install) is
            # left intact.
            pass

    def _select_payload_asset(
        self, release: Release, name: str, version: str
    ) -> ReleaseAsset:
        """Pick the platform/python-tagged payload asset from the release."""
        v = version if version.startswith("v") else version
        candidates: list[ReleaseAsset] = []
        for asset in release.assets:
            if asset.name == "manifest.json":
                continue
            if asset.name.endswith(".tar.gz") and name in asset.name and v in asset.name:
                candidates.append(asset)
        if not candidates:
            raise IntegrityError(
                f"release {release.tag} has no payload asset for {name} {version}"
            )
        # Prefer the asset matching our platform + python tag; fall back to
        # the first candidate (registry may ship platform-agnostic tarballs).
        plat = self.platform_tag
        ptag = self.python_tag
        for asset in candidates:
            if plat in asset.name and ptag in asset.name:
                return asset
        return candidates[0]

    # ------------------------------------------------------------------
    # list / info
    # ------------------------------------------------------------------

    def list_installed(self) -> list[InstalledExtension]:
        """Return the highest-version installed extension per name."""
        if not self.extensions_dir.is_dir():
            return []
        names = sorted(
            d.name for d in self.extensions_dir.iterdir() if d.is_dir()
        )
        out: list[InstalledExtension] = []
        for name in names:
            inst = self.latest_installed_version(name)
            if inst is not None:
                out.append(inst)
        return out

    def info(self, name: str) -> dict[str, Any]:
        """Return metadata for an installed extension, or registry hint."""
        inst = self.latest_installed_version(name)
        if inst is not None:
            return {
                "name": inst.name,
                "version": inst.version,
                "installed": True,
                "path": str(inst.path),
                "platform": inst.manifest.platform,
                "python_tag": inst.manifest.python_tag,
                "enables": list(inst.manifest.enables),
                "signer": inst.manifest.signer,
                "size_bytes": inst.size_bytes,
                "files": sorted(inst.manifest.sha256.keys()),
            }
        # Not installed: surface registry hint if first-party.
        for entry in self.registry.search():
            if entry.get("name") == name:
                return {"name": name, "installed": False, **entry}
        raise ExtensionNotFoundError(f"no such extension: {name}")

    # ------------------------------------------------------------------
    # remove
    # ------------------------------------------------------------------

    def remove(self, name: str) -> dict[str, Any]:
        """Delete all installed versions of ``name`` and record a tombstone."""
        base = self.extensions_dir / name
        if not base.is_dir():
            raise ExtensionNotFoundError(f"no such extension: {name}")
        versions_removed: list[str] = []
        for d in base.iterdir():
            if d.is_dir() and (d / "manifest.json").exists():
                versions_removed.append(d.name)
        shutil.rmtree(base)
        self._append_tombstone(name, versions_removed)
        return {"name": name, "removed_versions": versions_removed}

    def _append_tombstone(self, name: str, versions: list[str]) -> None:
        import datetime

        self.extensions_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "name": name,
            "versions": versions,
            "removed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "reason": "mnemosyne extension remove",
        }
        log_path = self.extensions_dir / _REMOVED_LOG_NAME
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    # ------------------------------------------------------------------
    # upgrade
    # ------------------------------------------------------------------

    def upgrade(self, name: Optional[str] = None, *, all_: bool = False) -> list[dict[str, Any]]:
        """Upgrade ``name`` (or ``--all``) to the latest registry release."""
        if not name and not all_:
            raise ValueError("upgrade requires either a name or --all")
        targets: list[str] = []
        if all_:
            targets = [inst.name for inst in self.list_installed()]
            if name and name not in targets:
                targets.append(name)
        elif name:
            targets = [name]
        results: list[dict[str, Any]] = []
        for tgt in targets:
            try:
                release = self.registry.latest_release(tgt)
                latest_version = release.tag.lstrip("v")
            except RegistryError as exc:
                results.append({"name": tgt, "status": "error", "error": str(exc)})
                continue
            inst = self.latest_installed_version(tgt)
            if inst is not None and _parse_semver(latest_version) <= _parse_semver(inst.version):
                results.append(
                    {
                        "name": tgt,
                        "status": "up-to-date",
                        "version": inst.version,
                    }
                )
                continue
            try:
                new_inst = self.install(tgt, version=latest_version, force=True)
                results.append(
                    {
                        "name": tgt,
                        "status": "upgraded",
                        "from": inst.version if inst else None,
                        "to": new_inst.version,
                    }
                )
            except (IntegrityError, ManifestError) as exc:
                results.append({"name": tgt, "status": "error", "error": str(exc)})
        return results

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def search(self, query: Optional[str] = None) -> list[dict[str, Any]]:
        entries = list(self.registry.search())
        if query:
            q = query.lower()
            entries = [
                e for e in entries
                if q in str(e.get("name", "")).lower()
                or q in str(e.get("description", "")).lower()
            ]
        # Annotate with installed version if present.
        for entry in entries:
            inst = self.latest_installed_version(entry.get("name", ""))
            entry = dict(entry)
            if inst is not None:
                entry["installed_version"] = inst.version
        return entries


# ---------------------------------------------------------------------------
# Tarball extraction with path-traversal hardening
# ---------------------------------------------------------------------------


def _safe_extract_tarball(archive: Path, dest: Path) -> None:
    """Extract a tarball refusing absolute paths and ``..`` traversal.

    Python 3.12+ ``tarfile.extractall`` accepts a ``filter=`` kwarg; for
    older interpreters we fall back to manual member validation. We never
    pass ``filter='data'`` blindly -- we want an explicit raise on any
    member that escapes ``dest``.
    """
    dest = Path(dest).resolve()
    with tarfile.open(str(archive), "r:gz") as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            try:
                target.relative_to(dest)
            except ValueError as exc:
                raise IntegrityError(
                    f"tarball member escapes payload dir: {member.name!r}"
                ) from exc
            if member.isdev() or member.issym():
                raise IntegrityError(
                    f"tarball member is a device/symlink: {member.name!r}"
                )
        # All members validated; extract.
        try:
            tar.extractall(path=str(dest), filter="data")  # type: ignore[arg-type]
        except TypeError:
            # Python <3.12: no filter kwarg.
            tar.extractall(path=str(dest))


def _parse_semver(version: str) -> tuple[int, ...]:
    """Parse a (possibly v-prefixed) semver-ish string into a sort key.

    Non-numeric components collapse to 0 so pre-release tags sort below
    their release counterpart.
    """
    v = version.lstrip("v").split("+", 1)[0]
    main = v.split("-", 1)[0]
    parts = main.split(".")
    out: list[int] = []
    for p in parts[:3]:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    # Pre-release suffix sorts below release (e.g. 1.0.0-rc1 < 1.0.0).
    pre = 0 if "-" not in v else -1
    return (*out, pre)


__all__ = [
    "ExtensionManager",
    "InstalledExtension",
    "IntegrityError",
    "ExtensionNotFoundError",
    "ManifestError",
    "sha256_file",
]

"""Runtime sys.path injection for installed extensions (REQ-PKG-003).

At ``mnemosyne`` startup, before CLI dispatch, every installed extension's
highest-version payload directory is prepended to ``sys.path``. This is
what makes ``import gliner`` / ``import fitz`` resolve to the sidecar
payload rather than failing with ImportError.

Safety contract (ISSUE-0007 security phase):

  - Only directories under ``<home>/extensions/<name>/<version>/`` are
    injected -- never arbitrary paths from a manifest field.
  - The version directory must contain a ``manifest.json`` that parses;
    a tampered or corrupted extension is skipped (with a stderr warning)
    rather than crashing startup.
  - The loader runs AFTER ``MNEMOSYNE_HOME`` is resolved and BEFORE any
    CLI handler touches optional deps. It is idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from mnemosyne.extensions.installer import ExtensionManager, _parse_semver
from mnemosyne.extensions.manifest import ManifestError


def _candidate_dirs(manager: ExtensionManager) -> list[Path]:
    """Return the highest-version payload directory per installed name.

    Only directories whose ``manifest.json`` parses successfully are
    considered. A removed (tombstoned) extension has no directory and is
    therefore skipped naturally.
    """
    if not manager.extensions_dir.is_dir():
        return []
    candidates: list[Path] = []
    for name_dir in manager.extensions_dir.iterdir():
        if not name_dir.is_dir() or name_dir.name.startswith("."):
            continue
        version_dirs = [
            d for d in name_dir.iterdir()
            if d.is_dir() and (d / "manifest.json").exists()
        ]
        if not version_dirs:
            continue
        # Highest semver wins.
        latest = max(version_dirs, key=lambda d: _parse_semver(d.name))
        candidates.append(latest)
    return candidates


def load_installed_extensions(
    home: Optional[Path] = None,
    *,
    paths: Optional[list[str]] = None,
) -> list[str]:
    """Inject installed extensions into ``sys.path`` and return added entries.

    Parameters
    ----------
    home:
        Override for the extensions home (defaults to ``MNEMOSYNE_HOME`` /
        ``~/.mnemosyne``). Mainly a test seam.
    paths:
        Override for ``sys.path`` (defaults to the real ``sys.path``).
        Test seam.
    """
    manager = ExtensionManager(home=home)
    target_paths = paths if paths is not None else sys.path
    added: list[str] = []
    for payload_dir in _candidate_dirs(manager):
        try:
            # Re-validate the manifest before injecting -- this is the
            # trust boundary. A corrupt manifest means we skip the dir
            # rather than crash the CLI.
            from mnemosyne.extensions.manifest import ExtensionManifest

            ExtensionManifest.from_path(payload_dir / "manifest.json")
        except ManifestError as exc:
            import sys as _sys

            print(
                f"warning: skipping extension {payload_dir.name}: corrupt manifest ({exc})",
                file=_sys.stderr,
            )
            continue
        except (OSError, ValueError) as exc:
            import sys as _sys

            print(
                f"warning: skipping extension {payload_dir.name}: {exc}",
                file=_sys.stderr,
            )
            continue
        path_str = str(payload_dir)
        if path_str not in target_paths:
            target_paths.insert(0, path_str)
            added.append(path_str)
    return added


__all__ = ["load_installed_extensions"]

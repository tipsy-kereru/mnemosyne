"""Extension sidecar mechanism (ISSUE-0007 / SPEC-PACKAGE-001 PACKAGE-B).

Provides the ``mnemosyne extension`` command group backing: a registry
client, payload installer with SHA256 + signed-manifest integrity
verification (REQ-PKG-010), and a runtime sys.path loader (REQ-PKG-003).

Public surface:
    - :class:`ExtensionManifest` -- typed manifest payload.
    - :class:`ExtensionManager` -- install/list/remove/upgrade/search/info.
    - :func:`load_installed_extensions` -- sys.path injection entry point.
"""

from mnemosyne.extensions.installer import (
    ExtensionManager,
    IntegrityError,
    ManifestError,
    ExtensionNotFoundError,
)
from mnemosyne.extensions.loader import load_installed_extensions
from mnemosyne.extensions.manifest import ExtensionManifest

__all__ = [
    "ExtensionManifest",
    "ExtensionManager",
    "IntegrityError",
    "ManifestError",
    "ExtensionNotFoundError",
    "load_installed_extensions",
]

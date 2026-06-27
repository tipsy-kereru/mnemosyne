"""
Mnemosyne Knowledge Graph - Local-first knowledge memory for AI agents.
"""

# Version resolution order:
#   1. importlib.metadata — works for pip / wheel installs (dist-info present).
#   2. mnemosyne._version — generated at PyOxidizer build time (scripts/build_binary.sh
#      bakes the pyproject version into _version.py), so the frozen binary reports
#      its real version instead of a hardcoded fallback.
#   3. unknown sentinel — only if neither is available (dev checkout without install).
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("mnemosyne-kg")
except PackageNotFoundError:
    try:
        from mnemosyne._version import __version__  # type: ignore[no-redef]
    except ImportError:
        __version__ = "0.0.0+unknown"

from mnemosyne.graph.knowledge_graph import Entity, Relation, Scope, KnowledgeGraph
from mnemosyne.graph.scope_manager import ScopeManager

__all__ = [
    "KnowledgeGraph",
    "ScopeManager",
    "Entity",
    "Relation",
    "Scope",
    "__version__",
]

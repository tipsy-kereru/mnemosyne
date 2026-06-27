"""
Mnemosyne Knowledge Graph - Local-first knowledge memory for AI agents.
"""

# Version resolution order:
#   1. mnemosyne._version — generated at PyOxidizer build time (scripts/
#      build_binary.sh bakes the pyproject version into _version.py), so the
#      frozen binary reports its real version. Checked FIRST because the frozen
#      importer's importlib.metadata may return a stale/empty value without
#      raising PackageNotFoundError.
#   2. importlib.metadata — works for pip / wheel installs (dist-info present).
#   3. unknown sentinel — dev checkout without install and without a baked version.
try:
    from mnemosyne._version import __version__  # type: ignore[no-redef]
except ImportError:
    try:
        from importlib.metadata import version as _pkg_version

        __version__ = _pkg_version("mnemosyne-kg")
    except Exception:
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

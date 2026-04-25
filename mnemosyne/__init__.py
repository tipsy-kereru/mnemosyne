"""
Mnemosyne Knowledge Graph - Local-first knowledge memory for AI agents.
"""

try:
    from importlib.metadata import version, PackageNotFoundError
    __version__ = version("mnemosyne-kg")
except PackageNotFoundError:
    __version__ = "0.1.0"

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

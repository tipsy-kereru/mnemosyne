"""
Knowledge Graph module with session-scoped memory support.
"""

from core.graph.knowledge_graph import Entity, Relation, Scope, KnowledgeGraph
from core.graph.scope_manager import ScopeManager

__all__ = [
    'Entity',
    'Relation',
    'Scope',
    'KnowledgeGraph',
    'ScopeManager',
]

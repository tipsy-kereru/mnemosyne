"""
Base protocol for language-specific extractors (SPEC-TS-001).

Defines the interface that all language extractors must implement.
"""

from typing import List, Optional, Protocol, runtime_checkable

from tree_sitter import Language, Tree

from mnemosyne.extraction.deterministic.code_parser import CodeEntity
from mnemosyne.extraction.deterministic.types import CallRelation, ImportEntity


@runtime_checkable
class LanguageExtractor(Protocol):
    """Protocol for language-specific AST extraction.

    Each language extractor must provide a ``language_name``, a ``grammar``,
    and methods to extract entities, imports, and call-graph edges from a
    parsed tree-sitter tree.
    """

    language_name: str
    grammar: Language

    def extract_entities(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CodeEntity]:
        """Extract code entities (functions, classes, etc.) from a parsed tree."""
        ...

    def extract_imports(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[ImportEntity]:
        """Extract import declarations from a parsed tree."""
        ...

    def extract_calls(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CallRelation]:
        """Extract call-graph edges from a parsed tree."""
        ...

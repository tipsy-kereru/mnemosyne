"""
Rust AST extractor using tree-sitter queries (SPEC-TS-001 Task 4).

Provides skeleton extraction for Rust. Gracefully handles missing grammar
packages by setting grammar to None.
"""

from typing import Any, List, Optional

from mnemosyne.extraction.deterministic.code_parser import CodeEntity
from mnemosyne.extraction.deterministic.types import CallRelation, ImportEntity


class RustExtractor:
    """Tree-sitter-based extractor for Rust source files."""

    language_name: str = "rust"

    def __init__(self) -> None:
        self.grammar: Optional[Any] = None
        self._load_grammar()

    def _load_grammar(self) -> None:
        """Attempt to load the Rust tree-sitter grammar."""
        try:
            from tree_sitter import Language
            import tree_sitter_rust as tsrust
            self.grammar = Language(tsrust.language())
        except ImportError:
            self.grammar = None

    def extract_entities(
        self,
        tree: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CodeEntity]:
        """Extract code entities from a parsed Rust tree."""
        if self.grammar is None:
            return []
        entities: List[CodeEntity] = []
        self._walk_entities(
            tree.root_node, source, file_path, scope_id, source_channel, entities,
        )
        return entities

    def _walk_entities(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
        entities: List[CodeEntity],
    ) -> None:
        for child in node.children:
            if child.type == "function_item":
                entities.append(self._extract_function(child, source, file_path, scope_id, source_channel))
            elif child.type == "struct_item":
                entities.append(self._extract_struct(child, source, file_path, scope_id, source_channel))
            elif child.type == "enum_item":
                entities.append(self._extract_enum(child, source, file_path, scope_id, source_channel))
            elif child.type == "trait_item":
                entities.append(self._extract_trait(child, source, file_path, scope_id, source_channel))
            elif child.type == "impl_item":
                self._extract_impl(child, source, file_path, scope_id, source_channel, entities)
            self._walk_entities(
                child, source, file_path, scope_id, source_channel, entities,
            )

    def _extract_function(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
    ) -> CodeEntity:
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode("utf-8") if name_node else "<unknown>"
        params_node = node.child_by_field_name("parameters")
        params = params_node.text.decode("utf-8") if params_node else ""
        return CodeEntity(
            type="function",
            name=name,
            language="rust",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            properties={
                "parameters": params,
                "extraction_method": "tree-sitter",
            },
            scope_id=scope_id,
            source_channel=source_channel,
        )

    def _extract_struct(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
    ) -> CodeEntity:
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode("utf-8") if name_node else "<unknown>"
        return CodeEntity(
            type="class",
            name=name,
            language="rust",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            properties={
                "kind": "struct",
                "extraction_method": "tree-sitter",
            },
            scope_id=scope_id,
            source_channel=source_channel,
        )

    def _extract_enum(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
    ) -> CodeEntity:
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode("utf-8") if name_node else "<unknown>"
        return CodeEntity(
            type="class",
            name=name,
            language="rust",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            properties={
                "kind": "enum",
                "extraction_method": "tree-sitter",
            },
            scope_id=scope_id,
            source_channel=source_channel,
        )

    def _extract_trait(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
    ) -> CodeEntity:
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode("utf-8") if name_node else "<unknown>"
        return CodeEntity(
            type="class",
            name=name,
            language="rust",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            properties={
                "kind": "trait",
                "extraction_method": "tree-sitter",
            },
            scope_id=scope_id,
            source_channel=source_channel,
        )

    def _extract_impl(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
        entities: List[CodeEntity],
    ) -> None:
        """Extract functions from impl blocks."""
        # body node contains the function items
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "function_item":
                    entities.append(self._extract_function(child, source, file_path, scope_id, source_channel))

    def extract_imports(
        self,
        tree: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[ImportEntity]:
        """Extract use declarations from Rust source."""
        if self.grammar is None:
            return []
        return []

    def extract_calls(
        self,
        tree: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CallRelation]:
        """Extract call-graph edges from Rust source."""
        if self.grammar is None:
            return []
        return []

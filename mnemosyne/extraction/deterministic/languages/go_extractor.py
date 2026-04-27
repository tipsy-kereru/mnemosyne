"""
Go AST extractor using tree-sitter queries (SPEC-TS-001 Task 4).

Provides skeleton extraction for Go. Gracefully handles missing grammar
packages by setting grammar to None.
"""

from typing import Any, List, Optional

from mnemosyne.extraction.deterministic.code_parser import CodeEntity
from mnemosyne.extraction.deterministic.types import CallRelation, ImportEntity


class GoExtractor:
    """Tree-sitter-based extractor for Go source files."""

    language_name: str = "go"

    def __init__(self) -> None:
        self.grammar: Optional[Any] = None
        self._load_grammar()

    def _load_grammar(self) -> None:
        """Attempt to load the Go tree-sitter grammar."""
        try:
            from tree_sitter import Language
            import tree_sitter_go as tsgo
            self.grammar = Language(tsgo.language())
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
        """Extract code entities from a parsed Go tree."""
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
            if child.type == "function_declaration":
                entities.append(self._extract_function(child, source, file_path, scope_id, source_channel))
            elif child.type == "method_declaration":
                entities.append(self._extract_method(child, source, file_path, scope_id, source_channel))
            elif child.type == "type_declaration":
                for spec in child.children:
                    if spec.type == "type_spec":
                        entities.append(self._extract_type_spec(spec, source, file_path, scope_id, source_channel))
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
            language="go",
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

    def _extract_method(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
    ) -> CodeEntity:
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode("utf-8") if name_node else "<unknown>"
        receiver_node = node.child_by_field_name("receiver")
        receiver = receiver_node.text.decode("utf-8") if receiver_node else None
        params_node = node.child_by_field_name("parameters")
        params = params_node.text.decode("utf-8") if params_node else ""
        return CodeEntity(
            type="function",
            name=name,
            language="go",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            properties={
                "receiver": receiver,
                "parameters": params,
                "extraction_method": "tree-sitter",
            },
            scope_id=scope_id,
            source_channel=source_channel,
        )

    def _extract_type_spec(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
    ) -> CodeEntity:
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode("utf-8") if name_node else "<unknown>"
        type_node = node.child_by_field_name("type")
        kind = "class"
        if type_node:
            if type_node.type == "interface_type":
                kind = "interface"
            elif type_node.type == "struct_type":
                kind = "struct"
        return CodeEntity(
            type="class",
            name=name,
            language="go",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            properties={
                "kind": kind,
                "extraction_method": "tree-sitter",
            },
            scope_id=scope_id,
            source_channel=source_channel,
        )

    def extract_imports(
        self,
        tree: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[ImportEntity]:
        """Extract import statements from Go source."""
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
        """Extract call-graph edges from Go source."""
        if self.grammar is None:
            return []
        return []

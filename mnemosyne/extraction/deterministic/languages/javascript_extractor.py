"""
JavaScript/TypeScript AST extractor using tree-sitter queries (SPEC-TS-001 Task 4).

Provides skeleton extraction for JS/TS. Gracefully handles missing grammar
packages by setting grammar to None.
"""

from typing import List, Optional

from tree_sitter import Language, Node, Tree

from mnemosyne.extraction.deterministic.code_parser import CodeEntity
from mnemosyne.extraction.deterministic.types import CallRelation, ImportEntity


class JavaScriptExtractor:
    """Tree-sitter-based extractor for JavaScript and TypeScript source files."""

    language_name: str = "javascript"

    def __init__(self) -> None:
        self.grammar: Optional[Language] = None
        self._load_grammar()

    def _load_grammar(self) -> None:
        """Attempt to load the JavaScript tree-sitter grammar."""
        try:
            import tree_sitter_javascript as tsjs
            self.grammar = Language(tsjs.language())
        except ImportError:
            self.grammar = None

    def extract_entities(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CodeEntity]:
        """Extract code entities from a parsed JS/TS tree."""
        if self.grammar is None:
            return []
        entities: List[CodeEntity] = []
        self._walk_entities(
            tree.root_node, source, file_path, scope_id, source_channel, entities,
        )
        return entities

    def _walk_entities(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
        entities: List[CodeEntity],
    ) -> None:
        for child in node.children:
            if child.type == "function_declaration":
                entities.append(self._extract_function(child, source, file_path, scope_id, source_channel))
            elif child.type == "class_declaration":
                entities.append(self._extract_class(child, source, file_path, scope_id, source_channel))
            elif child.type == "lexical_declaration":
                # Arrow functions: const f = () => ...
                for sub in child.children:
                    if sub.type == "variable_declarator":
                        name_node = sub.child_by_field_name("name")
                        value_node = sub.child_by_field_name("value")
                        if name_node and value_node and value_node.type in (
                            "arrow_function", "function_expression",
                        ):
                            entities.append(CodeEntity(
                                type="function",
                                name=(name_node.text or b"").decode("utf-8"),
                                language="javascript",
                                file_path=file_path,
                                line_start=name_node.start_point[0] + 1,
                                line_end=name_node.end_point[0] + 1,
                                properties={"extraction_method": "tree-sitter"},
                                scope_id=scope_id,
                                source_channel=source_channel,
                            ))
            self._walk_entities(
                child, source, file_path, scope_id, source_channel, entities,
            )

    def _extract_function(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
    ) -> CodeEntity:
        name_node = node.child_by_field_name("name")
        name = (name_node.text or b"").decode("utf-8") if name_node else "<anonymous>"
        params_node = node.child_by_field_name("parameters")
        params = (params_node.text or b"").decode("utf-8") if params_node else ""
        return CodeEntity(
            type="function",
            name=name,
            language="javascript",
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

    def _extract_class(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
    ) -> CodeEntity:
        name_node = node.child_by_field_name("name")
        name = (name_node.text or b"").decode("utf-8") if name_node else "<anonymous>"
        # Check for extends clause
        parent = node.child_by_field_name("parent")
        extends = (parent.text or b"").decode("utf-8") if parent else None
        return CodeEntity(
            type="class",
            name=name,
            language="javascript",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            properties={
                "extends": extends,
                "extraction_method": "tree-sitter",
            },
            scope_id=scope_id,
            source_channel=source_channel,
        )

    def extract_imports(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[ImportEntity]:
        """Extract import statements from JS/TS source."""
        if self.grammar is None:
            return []
        # Placeholder: will be implemented in Task 5
        return []

    def extract_calls(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CallRelation]:
        """Extract call-graph edges from JS/TS source."""
        if self.grammar is None:
            return []
        # Placeholder: will be implemented in Task 5
        return []

"""
Python AST extractor using tree-sitter queries (SPEC-TS-001 Task 3).

Extracts functions, classes, decorators, docstrings, McCabe complexity,
import declarations, and call-graph edges from Python source files.
"""

from typing import Any, Dict, List, Optional

import tree_sitter_python as tspython
from tree_sitter import Language, Query, QueryCursor

from mnemosyne.extraction.deterministic.code_parser import CodeEntity
from mnemosyne.extraction.deterministic.types import CallRelation, ImportEntity

# Branch-increasing node types used for McCabe complexity calculation.
_MCCABE_BRANCH_TYPES = frozenset({
    "if_statement",
    "elif_clause",
    "for_statement",
    "while_statement",
    "except_clause",
    "with_statement",
    "boolean_operator",  # and / or
    "ternary_expression",
})


def _count_complexity(node) -> int:
    """Recursively count McCabe complexity-branching nodes under *node*."""
    count = 0
    if node.type in _MCCABE_BRANCH_TYPES:
        count += 1
    for child in node.children:
        count += _count_complexity(child)
    return count


class PythonExtractor:
    """Tree-sitter-based extractor for Python source files."""

    language_name: str = "python"

    def __init__(self) -> None:
        self.grammar = Language(tspython.language())

    # ------------------------------------------------------------------
    # Entity extraction
    # ------------------------------------------------------------------

    def extract_entities(
        self,
        tree: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CodeEntity]:
        """Extract functions and classes from a parsed Python tree."""
        entities: List[CodeEntity] = []
        root = tree.root_node

        # Walk all function_definition and class_definition nodes
        self._walk_entities(root, source, file_path, scope_id, source_channel, entities)
        return entities

    def _walk_entities(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
        entities: List[CodeEntity],
        parent_name: Optional[str] = None,
    ) -> None:
        """Recursively walk the tree, extracting functions and classes."""
        for child in node.children:
            if child.type == "function_definition":
                entity = self._extract_function(
                    child, source, file_path, scope_id, source_channel, parent_name,
                )
                entities.append(entity)
                # Recurse into function body for nested definitions
                func_name = entity.name
                body = child.child_by_field_name("body")
                if body:
                    self._walk_entities(
                        body, source, file_path, scope_id, source_channel,
                        entities, parent_name=func_name,
                    )

            elif child.type == "class_definition":
                entity = self._extract_class(
                    child, source, file_path, scope_id, source_channel,
                )
                entities.append(entity)
                # Recurse into class body for methods
                body = child.child_by_field_name("body")
                if body:
                    class_name = entity.name
                    self._walk_entities(
                        body, source, file_path, scope_id, source_channel,
                        entities, parent_name=class_name,
                    )

            elif child.type == "decorated_definition":
                # Unwrap the decorator and process the inner definition
                self._handle_decorated(
                    child, source, file_path, scope_id, source_channel,
                    entities, parent_name,
                )

            else:
                # Keep walking for top-level nodes
                self._walk_entities(
                    child, source, file_path, scope_id, source_channel,
                    entities, parent_name,
                )

    def _handle_decorated(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
        entities: List[CodeEntity],
        parent_name: Optional[str],
    ) -> None:
        """Process a decorated_definition node."""
        # Collect decorator names from direct decorator children
        decorator_names: List[str] = []
        inner_node = None
        for child in node.children:
            if child.type == "decorator":
                # The decorator node's children are: @, identifier
                # Or: @, attribute (e.g. @foo.bar)
                dec_name = ""
                for sub in child.children:
                    if sub.type in ("identifier", "attribute"):
                        raw = sub.text.decode("utf-8")
                        dec_name = raw.split("(")[0].split(".")[-1].strip()
                        break
                if dec_name:
                    decorator_names.append(dec_name)
            elif child.type in ("function_definition", "class_definition"):
                inner_node = child

        if inner_node is None:
            return

        if inner_node.type == "function_definition":
            entity = self._extract_function(
                inner_node, source, file_path, scope_id, source_channel, parent_name,
            )
            entity.properties["decorators"] = decorator_names
            entities.append(entity)
            body = inner_node.child_by_field_name("body")
            if body:
                self._walk_entities(
                    body, source, file_path, scope_id, source_channel,
                    entities, parent_name=entity.name,
                )

        elif inner_node.type == "class_definition":
            entity = self._extract_class(
                inner_node, source, file_path, scope_id, source_channel,
            )
            entity.properties["decorators"] = decorator_names
            entities.append(entity)
            body = inner_node.child_by_field_name("body")
            if body:
                self._walk_entities(
                    body, source, file_path, scope_id, source_channel,
                    entities, parent_name=entity.name,
                )

    def _extract_function(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
        parent_name: Optional[str],
    ) -> CodeEntity:
        """Build a CodeEntity from a function_definition node."""
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode("utf-8") if name_node else "<unknown>"

        params_node = node.child_by_field_name("parameters")
        params = params_node.text.decode("utf-8") if params_node else ""

        ret_node = node.child_by_field_name("return_type")
        return_type = ret_node.text.decode("utf-8") if ret_node else None

        # Detect async from preceding sibling or keyword
        is_async = "async" in node.text.decode("utf-8")[:30]

        # Extract docstring
        docstring = self._extract_docstring(node)

        # McCabe complexity
        complexity = 1 + _count_complexity(node)

        properties: Dict[str, Any] = {
            "parameters": params,
            "return_type": return_type,
            "is_async": is_async,
            "complexity": complexity,
            "extraction_method": "tree-sitter",
        }
        if docstring:
            properties["docstring"] = docstring
        if parent_name:
            properties["parent"] = parent_name

        line_start = node.start_point[0] + 1
        line_end = node.end_point[0] + 1

        return CodeEntity(
            type="function",
            name=name,
            language="python",
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            properties=properties,
            scope_id=scope_id,
            source_channel=source_channel,
        )

    def _extract_class(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
    ) -> CodeEntity:
        """Build a CodeEntity from a class_definition node."""
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode("utf-8") if name_node else "<unknown>"

        # Extract base classes from the superclasses field
        bases: List[str] = []
        arg_list = node.child_by_field_name("superclasses")
        if arg_list:
            for child in arg_list.children:
                if child.type in ("identifier", "attribute", "subscript"):
                    bases.append(child.text.decode("utf-8"))

        docstring = self._extract_docstring(node)

        properties: Dict[str, Any] = {
            "bases": bases,
            "extraction_method": "tree-sitter",
        }
        if docstring:
            properties["docstring"] = docstring

        line_start = node.start_point[0] + 1
        line_end = node.end_point[0] + 1

        return CodeEntity(
            type="class",
            name=name,
            language="python",
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            properties=properties,
            scope_id=scope_id,
            source_channel=source_channel,
        )

    def _extract_docstring(self, node: Any) -> Optional[str]:
        """Extract docstring from the first statement of a function/class body."""
        body = node.child_by_field_name("body")
        if not body or not body.children:
            return None
        first = body.children[0]
        if first.type == "expression_statement" and first.children:
            inner = first.children[0]
            if inner.type == "string":
                text = inner.text.decode("utf-8")
                # Strip triple-quote delimiters
                for q in ('"""', "'''"):
                    if text.startswith(q) and text.endswith(q):
                        text = text[len(q):-len(q)]
                        break
                return text.strip()
        return None

    # ------------------------------------------------------------------
    # Import extraction
    # ------------------------------------------------------------------

    def extract_imports(
        self,
        tree: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[ImportEntity]:
        """Extract import statements from a parsed Python tree."""
        imports: List[ImportEntity] = []
        query = Query(
            self.grammar,
            """
            [
              (import_statement
                name: (dotted_name) @module)
              (import_from_statement
                module_name: (dotted_name) @from_module
                name: (dotted_name) @imported_name)
              (import_from_statement
                module_name: (relative_import) @relative_module)
            ]
            """,
        )
        cursor = QueryCursor(query)
        matches = cursor.matches(tree.root_node)

        seen: set = set()
        for _pattern_idx, captures in matches:
            module_node = captures.get("module", [None])[0]
            from_module_node = captures.get("from_module", [None])[0]
            imported_name_node = captures.get("imported_name", [None])[0]
            relative_node = captures.get("relative_module", [None])[0]

            if module_node:
                # import X
                node_text = module_node.text
                assert node_text is not None, "node.text should not be None"
                mod = node_text.decode("utf-8")
                key = (mod, mod)
                if key not in seen:
                    seen.add(key)
                    imports.append(ImportEntity(
                        source_file=file_path,
                        module_path=mod,
                        imported_names=[mod],
                        is_local=False,
                        line_number=module_node.start_point[0] + 1,
                        scope_id=scope_id,
                        source_channel=source_channel,
                    ))

            elif from_module_node:
                # from X import Y
                mod_text = from_module_node.text
                assert mod_text is not None, "node.text should not be None"
                mod = mod_text.decode("utf-8")
                if imported_name_node:
                    imported_text = imported_name_node.text
                    assert imported_text is not None, "node.text should not be None"
                    imported = imported_text.decode("utf-8")
                else:
                    imported = ""
                key = (mod, imported)
                if key not in seen:
                    seen.add(key)
                    imports.append(ImportEntity(
                        source_file=file_path,
                        module_path=mod,
                        imported_names=[imported] if imported else [],
                        is_local=False,
                        line_number=from_module_node.start_point[0] + 1,
                        scope_id=scope_id,
                        source_channel=source_channel,
                    ))

            elif relative_node:
                # from . import X  or  from ..foo import X
                rel_text = relative_node.text
                assert rel_text is not None, "node.text should not be None"
                mod = rel_text.decode("utf-8")
                key = ("relative", mod)
                if key not in seen:
                    seen.add(key)
                    imports.append(ImportEntity(
                        source_file=file_path,
                        module_path=mod,
                        imported_names=[],
                        is_local=True,
                        line_number=relative_node.start_point[0] + 1,
                        scope_id=scope_id,
                        source_channel=source_channel,
                    ))

        return imports

    # ------------------------------------------------------------------
    # Call-graph extraction
    # ------------------------------------------------------------------

    def extract_calls(
        self,
        tree: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[CallRelation]:
        """Extract function/method call edges from a parsed Python tree."""
        calls: List[CallRelation] = []
        # Find all call nodes and track their enclosing function
        self._walk_calls(tree.root_node, source, file_path, scope_id, source_channel, calls)
        return calls

    def _walk_calls(
        self,
        node: Any,
        source: bytes,
        file_path: str,
        scope_id: Optional[str],
        source_channel: Optional[str],
        calls: List[CallRelation],
        caller_name: str = "<module>",
    ) -> None:
        """Walk the tree, tracking call nodes and their enclosing function context."""
        for child in node.children:
            if child.type == "function_definition":
                name_node = child.child_by_field_name("name")
                fn_name = name_node.text.decode("utf-8") if name_node else "<anonymous>"
                body = child.child_by_field_name("body")
                if body:
                    self._walk_calls(
                        body, source, file_path, scope_id, source_channel,
                        calls, caller_name=fn_name,
                    )
            elif child.type == "class_definition":
                body = child.child_by_field_name("body")
                if body:
                    self._walk_calls(
                        body, source, file_path, scope_id, source_channel,
                        calls, caller_name=caller_name,
                    )
            elif child.type == "decorated_definition":
                # Skip decorator node, walk inner definition
                for sub in child.children:
                    if sub.type in ("function_definition", "class_definition"):
                        self._walk_calls(
                            sub, source, file_path, scope_id, source_channel,
                            calls, caller_name=caller_name,
                        )
            elif child.type == "call":
                callee = self._callee_name(child)
                if callee:
                    calls.append(CallRelation(
                        caller_name=caller_name,
                        caller_file=file_path,
                        callee_name=callee,
                        callee_line=child.start_point[0] + 1,
                        call_type="method_call" if "." in callee else "function_call",
                        scope_id=scope_id,
                        source_channel=source_channel,
                    ))
                # Walk into call arguments for nested calls
                for sub in child.children:
                    self._walk_calls(
                        sub, source, file_path, scope_id, source_channel,
                        calls, caller_name=caller_name,
                    )
            else:
                self._walk_calls(
                    child, source, file_path, scope_id, source_channel,
                    calls, caller_name=caller_name,
                )

    @staticmethod
    def _callee_name(call_node: Any) -> str:
        """Extract the callee name from a call node."""
        func = call_node.child_by_field_name("function")
        if func:
            return func.text.decode("utf-8")
        return ""

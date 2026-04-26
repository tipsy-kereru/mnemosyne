"""
Tests for tree-sitter extraction data structures (SPEC-TS-001 Task 1).

Covers: ParseResult, ImportEntity, CallRelation dataclasses and their
default values, construction, and field access patterns.
"""

import pytest

from mnemosyne.extraction.deterministic.code_parser import CodeEntity


class TestCodeEntity:
    """Verify the existing CodeEntity dataclass still works."""

    def test_code_entity_creation(self):
        """CodeEntity can be created with all fields."""
        entity = CodeEntity(
            type="function",
            name="my_func",
            language="python",
            file_path="/test.py",
            line_start=1,
            line_end=5,
            properties={"parameters": "x, y"},
            scope_id="session-1",
            source_channel="cli",
        )
        assert entity.type == "function"
        assert entity.name == "my_func"
        assert entity.language == "python"
        assert entity.file_path == "/test.py"
        assert entity.line_start == 1
        assert entity.line_end == 5
        assert entity.properties == {"parameters": "x, y"}
        assert entity.scope_id == "session-1"
        assert entity.source_channel == "cli"

    def test_code_entity_optional_fields_default_none(self):
        """CodeEntity scope_id and source_channel default to None."""
        entity = CodeEntity(
            type="function",
            name="f",
            language="python",
            file_path="/a.py",
            line_start=1,
            line_end=1,
            properties={},
        )
        assert entity.scope_id is None
        assert entity.source_channel is None


class TestImportEntity:
    """Tests for ImportEntity dataclass."""

    def test_import_entity_creation(self):
        """ImportEntity stores import metadata."""
        from mnemosyne.extraction.deterministic.types import ImportEntity

        imp = ImportEntity(
            source_file="/test.py",
            module_path="os.path",
            imported_names=["join", "exists"],
            is_local=False,
            line_number=3,
        )
        assert imp.source_file == "/test.py"
        assert imp.module_path == "os.path"
        assert imp.imported_names == ["join", "exists"]
        assert imp.is_local is False
        assert imp.line_number == 3

    def test_import_entity_scope_fields(self):
        """ImportEntity has optional scope_id and source_channel."""
        from mnemosyne.extraction.deterministic.types import ImportEntity

        imp = ImportEntity(
            source_file="/test.py",
            module_path="json",
            imported_names=[],
            is_local=False,
            line_number=1,
            scope_id="session-42",
            source_channel="vscode",
        )
        assert imp.scope_id == "session-42"
        assert imp.source_channel == "vscode"

    def test_import_entity_scope_defaults_none(self):
        """ImportEntity scope_id and source_channel default to None."""
        from mnemosyne.extraction.deterministic.types import ImportEntity

        imp = ImportEntity(
            source_file="/a.py",
            module_path="sys",
            imported_names=["path"],
            is_local=False,
            line_number=1,
        )
        assert imp.scope_id is None
        assert imp.source_channel is None

    def test_import_entity_single_name(self):
        """ImportEntity with a single imported name."""
        from mnemosyne.extraction.deterministic.types import ImportEntity

        imp = ImportEntity(
            source_file="/a.py",
            module_path="os",
            imported_names=["os"],
            is_local=False,
            line_number=1,
        )
        assert imp.imported_names == ["os"]

    def test_import_entity_local_import(self):
        """ImportEntity marks relative imports as local."""
        from mnemosyne.extraction.deterministic.types import ImportEntity

        imp = ImportEntity(
            source_file="/pkg/a.py",
            module_path=".utils",
            imported_names=["helper"],
            is_local=True,
            line_number=2,
        )
        assert imp.is_local is True


class TestCallRelation:
    """Tests for CallRelation dataclass."""

    def test_call_relation_creation(self):
        """CallRelation stores call-graph edges."""
        from mnemosyne.extraction.deterministic.types import CallRelation

        call = CallRelation(
            caller_name="my_func",
            caller_file="/test.py",
            callee_name="helper",
            callee_line=10,
            call_type="function_call",
        )
        assert call.caller_name == "my_func"
        assert call.caller_file == "/test.py"
        assert call.callee_name == "helper"
        assert call.callee_line == 10
        assert call.call_type == "function_call"

    def test_call_relation_scope_fields(self):
        """CallRelation has optional scope_id and source_channel."""
        from mnemosyne.extraction.deterministic.types import CallRelation

        call = CallRelation(
            caller_name="main",
            caller_file="/a.py",
            callee_name="run",
            callee_line=5,
            call_type="function_call",
            scope_id="s1",
            source_channel="cli",
        )
        assert call.scope_id == "s1"
        assert call.source_channel == "cli"

    def test_call_relation_scope_defaults_none(self):
        """CallRelation scope_id and source_channel default to None."""
        from mnemosyne.extraction.deterministic.types import CallRelation

        call = CallRelation(
            caller_name="main",
            caller_file="/a.py",
            callee_name="run",
            callee_line=5,
            call_type="function_call",
        )
        assert call.scope_id is None
        assert call.source_channel is None

    def test_call_relation_method_call_type(self):
        """CallRelation tracks method vs function call type."""
        from mnemosyne.extraction.deterministic.types import CallRelation

        call = CallRelation(
            caller_name="MyClass.process",
            caller_file="/a.py",
            callee_name="validate",
            callee_line=12,
            call_type="method_call",
        )
        assert call.call_type == "method_call"


class TestParseResult:
    """Tests for ParseResult dataclass."""

    def test_parse_result_full_construction(self):
        """ParseResult holds entities, imports, calls, and metadata."""
        from mnemosyne.extraction.deterministic.types import ParseResult

        entity = CodeEntity(
            type="function",
            name="f",
            language="python",
            file_path="/test.py",
            line_start=1,
            line_end=3,
            properties={},
        )
        result = ParseResult(
            entities=[entity],
            file_path="/test.py",
            language="python",
            content_hash="abc123",
            extraction_method="tree-sitter",
        )
        assert len(result.entities) == 1
        assert result.entities[0].name == "f"
        assert result.file_path == "/test.py"
        assert result.language == "python"
        assert result.content_hash == "abc123"
        assert result.extraction_method == "tree-sitter"

    def test_parse_result_default_empty_collections(self):
        """ParseResult defaults to empty lists for entities, imports, calls."""
        from mnemosyne.extraction.deterministic.types import ParseResult

        result = ParseResult(
            file_path="/test.py",
            language="python",
            content_hash="hash",
            extraction_method="regex",
        )
        assert result.entities == []
        assert result.imports == []
        assert result.calls == []

    def test_parse_result_default_empty_strings(self):
        """ParseResult defaults to empty strings for metadata fields."""
        from mnemosyne.extraction.deterministic.types import ParseResult

        result = ParseResult()
        assert result.file_path == ""
        assert result.language == ""
        assert result.content_hash == ""
        assert result.extraction_method == ""
        assert result.entities == []
        assert result.imports == []
        assert result.calls == []

    def test_parse_result_with_imports_and_calls(self):
        """ParseResult can carry imports and calls alongside entities."""
        from mnemosyne.extraction.deterministic.types import (
            CallRelation,
            ImportEntity,
            ParseResult,
        )

        imp = ImportEntity(
            source_file="/test.py",
            module_path="os",
            imported_names=["path"],
            is_local=False,
            line_number=1,
        )
        call = CallRelation(
            caller_name="main",
            caller_file="/test.py",
            callee_name="run",
            callee_line=5,
            call_type="function_call",
        )
        result = ParseResult(
            imports=[imp],
            calls=[call],
            file_path="/test.py",
            language="python",
            content_hash="h",
            extraction_method="tree-sitter",
        )
        assert len(result.imports) == 1
        assert result.imports[0].module_path == "os"
        assert len(result.calls) == 1
        assert result.calls[0].callee_name == "run"

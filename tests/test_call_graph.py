"""
Tests for call-graph extraction (SPEC-TS-001 Task 5).

Covers: Python call extraction, caller context tracking,
method vs function call types.
"""

import pytest

from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor


@pytest.fixture
def python_extractor():
    """Create a PythonExtractor for testing."""
    from mnemosyne.extraction.deterministic.languages.python_extractor import (
        PythonExtractor,
    )
    return PythonExtractor()


def _parse_python(source: str, extractor):
    """Parse Python source and return (tree, source_bytes)."""
    from tree_sitter import Parser
    parser = Parser(extractor.grammar)
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    return tree, source_bytes


class TestPythonCallGraph:
    """Tests for Python call-graph extraction."""

    def test_simple_function_call(self, python_extractor):
        """Extract a simple function call."""
        source = "def foo():\n    bar()\n"
        tree, src = _parse_python(source, python_extractor)
        calls = python_extractor.extract_calls(tree, src, "/test.py")
        assert len(calls) >= 1
        assert any(c.callee_name == "bar" for c in calls)

    def test_caller_context(self, python_extractor):
        """Calls inside a function track the function as caller."""
        source = "def foo():\n    bar()\n"
        tree, src = _parse_python(source, python_extractor)
        calls = python_extractor.extract_calls(tree, src, "/test.py")
        bar_calls = [c for c in calls if c.callee_name == "bar"]
        assert len(bar_calls) >= 1
        assert bar_calls[0].caller_name == "foo"

    def test_method_call_type(self, python_extractor):
        """obj.method() calls are classified as method_call."""
        source = "def foo():\n    obj.bar()\n"
        tree, src = _parse_python(source, python_extractor)
        calls = python_extractor.extract_calls(tree, src, "/test.py")
        method_calls = [c for c in calls if "bar" in c.callee_name]
        assert len(method_calls) >= 1
        assert method_calls[0].call_type == "method_call"

    def test_function_call_type(self, python_extractor):
        """bare_func() calls are classified as function_call."""
        source = "def foo():\n    bar()\n"
        tree, src = _parse_python(source, python_extractor)
        calls = python_extractor.extract_calls(tree, src, "/test.py")
        func_calls = [c for c in calls if c.callee_name == "bar"]
        assert len(func_calls) >= 1
        assert func_calls[0].call_type == "function_call"

    def test_call_line_number(self, python_extractor):
        """Call callee_line matches the actual line number."""
        source = "def foo():\n    bar()\n"
        tree, src = _parse_python(source, python_extractor)
        calls = python_extractor.extract_calls(tree, src, "/test.py")
        bar_calls = [c for c in calls if c.callee_name == "bar"]
        assert bar_calls[0].callee_line == 2

    def test_call_with_scope(self, python_extractor):
        """Call carries scope_id and source_channel."""
        source = "def foo():\n    bar()\n"
        tree, src = _parse_python(source, python_extractor)
        calls = python_extractor.extract_calls(
            tree, src, "/test.py", scope_id="s1", source_channel="cli",
        )
        assert all(c.scope_id == "s1" for c in calls)
        assert all(c.source_channel == "cli" for c in calls)

    def test_module_level_call(self, python_extractor):
        """Calls at module level have caller_name='<module>'."""
        source = "bar()\n"
        tree, src = _parse_python(source, python_extractor)
        calls = python_extractor.extract_calls(tree, src, "/test.py")
        assert len(calls) >= 1
        assert calls[0].caller_name == "<module>"

    def test_multiple_calls_in_function(self, python_extractor):
        """Extract multiple calls from a single function."""
        source = "def foo():\n    bar()\n    baz()\n"
        tree, src = _parse_python(source, python_extractor)
        calls = python_extractor.extract_calls(tree, src, "/test.py")
        callee_names = {c.callee_name for c in calls}
        assert "bar" in callee_names
        assert "baz" in callee_names

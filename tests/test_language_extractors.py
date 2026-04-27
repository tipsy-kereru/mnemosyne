"""
Tests for language-specific AST extractors (SPEC-TS-001 Task 3).

Covers: Python extractor for functions, classes, decorators, async detection,
nested functions, docstrings, McCabe complexity, and extraction_method tagging.
"""

import pytest



@pytest.fixture
def python_extractor():
    """Create a PythonExtractor instance."""
    from mnemosyne.extraction.deterministic.languages.python_extractor import (
        PythonExtractor,
    )

    return PythonExtractor()


def _parse_python(source: str, extractor):
    """Helper: parse Python source and return (tree, source_bytes)."""
    from tree_sitter import Parser

    parser = Parser(extractor.grammar)
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    return tree, source_bytes


class TestPythonFunctionExtraction:
    """Tests for Python function extraction via tree-sitter."""

    def test_simple_function(self, python_extractor):
        """Extract a simple top-level function definition."""
        source = "def hello():\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "hello"

    def test_function_with_parameters(self, python_extractor):
        """Extract function parameters as a property."""
        source = "def add(a, b):\n    return a + b\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert len(funcs) == 1
        assert "parameters" in funcs[0].properties

    def test_function_with_return_type(self, python_extractor):
        """Extract function return type annotation."""
        source = "def get_name() -> str:\n    return 'x'\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert len(funcs) == 1
        assert "return_type" in funcs[0].properties

    def test_async_function(self, python_extractor):
        """Detect async function definitions."""
        source = "async def fetch():\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert len(funcs) == 1
        assert funcs[0].properties.get("is_async") is True

    def test_sync_function_not_async(self, python_extractor):
        """Sync functions have is_async=False."""
        source = "def sync_func():\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert funcs[0].properties.get("is_async") is False

    def test_multiple_functions(self, python_extractor):
        """Extract multiple function definitions from one file."""
        source = "def foo():\n    pass\n\ndef bar():\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert len(funcs) == 2
        names = {f.name for f in funcs}
        assert names == {"foo", "bar"}


class TestPythonClassExtraction:
    """Tests for Python class extraction via tree-sitter."""

    def test_simple_class(self, python_extractor):
        """Extract a simple class definition."""
        source = "class Foo:\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        classes = [e for e in entities if e.type == "class"]
        assert len(classes) == 1
        assert classes[0].name == "Foo"

    def test_class_with_bases(self, python_extractor):
        """Extract class inheritance (base classes)."""
        source = "class Child(Parent):\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        classes = [e for e in entities if e.type == "class"]
        assert len(classes) == 1
        assert "bases" in classes[0].properties
        assert len(classes[0].properties["bases"]) >= 1

    def test_class_with_multiple_bases(self, python_extractor):
        """Extract class with multiple base classes."""
        source = "class C(A, B):\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        classes = [e for e in entities if e.type == "class"]
        assert len(classes[0].properties["bases"]) >= 2


class TestPythonDecoratorExtraction:
    """Tests for Python decorator extraction."""

    def test_function_with_decorator(self, python_extractor):
        """Extract decorators on functions."""
        source = "@property\ndef name(self):\n    return self._name\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert len(funcs) == 1
        assert "decorators" in funcs[0].properties
        assert "property" in funcs[0].properties["decorators"]

    def test_class_with_decorator(self, python_extractor):
        """Extract decorators on classes."""
        source = "@dataclass\nclass Config:\n    x: int = 0\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        classes = [e for e in entities if e.type == "class"]
        assert len(classes) == 1
        assert "decorators" in classes[0].properties
        assert "dataclass" in classes[0].properties["decorators"]

    def test_multiple_decorators(self, python_extractor):
        """Extract multiple decorators on a single definition."""
        source = "@decorator1\n@decorator2\ndef f():\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert len(funcs) == 1
        decs = funcs[0].properties.get("decorators", [])
        assert "decorator1" in decs
        assert "decorator2" in decs


class TestPythonNestedFunction:
    """Tests for nested function extraction with parent tracking."""

    def test_nested_function_parent(self, python_extractor):
        """Nested functions track their parent function."""
        source = "def outer():\n    def inner():\n        pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = {e.name: e for e in entities if e.type == "function"}
        assert "outer" in funcs
        assert "inner" in funcs
        assert funcs["inner"].properties.get("parent") == "outer"


class TestPythonDocstring:
    """Tests for docstring extraction."""

    def test_function_docstring(self, python_extractor):
        """Extract docstring from function body."""
        source = 'def foo():\n    """This is a docstring."""\n    pass\n'
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert len(funcs) == 1
        assert "docstring" in funcs[0].properties
        assert "This is a docstring" in funcs[0].properties["docstring"]

    def test_class_docstring(self, python_extractor):
        """Extract docstring from class body."""
        source = 'class Foo:\n    """A class docstring."""\n    pass\n'
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        classes = [e for e in entities if e.type == "class"]
        assert len(classes) == 1
        assert "docstring" in classes[0].properties


class TestPythonComplexity:
    """Tests for McCabe complexity calculation."""

    def test_simple_function_complexity(self, python_extractor):
        """A function with no branches has complexity 1."""
        source = "def simple():\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert funcs[0].properties.get("complexity") == 1

    def test_if_statement_complexity(self, python_extractor):
        """An if statement adds 1 to complexity."""
        source = "def check(x):\n    if x:\n        pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert funcs[0].properties.get("complexity", 1) >= 2


class TestPythonExtractionMethod:
    """Tests for extraction_method field."""

    def test_extraction_method_is_tree_sitter(self, python_extractor):
        """Extraction via tree-sitter sets extraction_method='tree-sitter'."""
        source = "def f():\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        assert all(e.properties.get("extraction_method") == "tree-sitter" for e in entities)


class TestPythonEntityLineNumbers:
    """Tests for correct line number extraction."""

    def test_line_start_correct(self, python_extractor):
        """Entity line_start matches actual source line (1-based)."""
        source = "\n\ndef f():\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/test.py")
        funcs = [e for e in entities if e.type == "function"]
        assert len(funcs) == 1
        assert funcs[0].line_start == 3

    def test_file_path_propagated(self, python_extractor):
        """Entity file_path matches what was passed to extract_entities."""
        source = "def f():\n    pass\n"
        tree, src = _parse_python(source, python_extractor)
        entities = python_extractor.extract_entities(tree, src, "/some/path.py")
        assert all(e.file_path == "/some/path.py" for e in entities)

"""
Tests for import extraction across languages (SPEC-TS-001 Task 5).

Covers: Python import/import-from/relative, JS import patterns,
local vs external classification.
"""

import pytest



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


class TestPythonImportExtraction:
    """Tests for Python import statement extraction."""

    def test_import_statement(self, python_extractor):
        """Extract 'import os' as an ImportEntity."""
        source = "import os\n"
        tree, src = _parse_python(source, python_extractor)
        imports = python_extractor.extract_imports(tree, src, "/test.py")
        assert len(imports) >= 1
        assert any(imp.module_path == "os" for imp in imports)

    def test_from_import_statement(self, python_extractor):
        """Extract 'from os.path import join'."""
        source = "from os.path import join\n"
        tree, src = _parse_python(source, python_extractor)
        imports = python_extractor.extract_imports(tree, src, "/test.py")
        assert len(imports) >= 1
        from_imports = [i for i in imports if i.module_path == "os.path"]
        assert len(from_imports) >= 1

    def test_relative_import_is_local(self, python_extractor):
        """Relative imports are classified as local."""
        source = "from . import utils\n"
        tree, src = _parse_python(source, python_extractor)
        imports = python_extractor.extract_imports(tree, src, "/test.py")
        local_imports = [i for i in imports if i.is_local]
        assert len(local_imports) >= 1

    def test_stdlib_import_is_not_local(self, python_extractor):
        """Standard library imports are not local."""
        source = "import json\n"
        tree, src = _parse_python(source, python_extractor)
        imports = python_extractor.extract_imports(tree, src, "/test.py")
        non_local = [i for i in imports if not i.is_local]
        assert len(non_local) >= 1

    def test_import_line_number(self, python_extractor):
        """Import line_number matches source position."""
        source = "\nimport os\n"
        tree, src = _parse_python(source, python_extractor)
        imports = python_extractor.extract_imports(tree, src, "/test.py")
        assert len(imports) >= 1
        assert imports[0].line_number == 2

    def test_import_source_file(self, python_extractor):
        """Import source_file matches the file_path parameter."""
        source = "import os\n"
        tree, src = _parse_python(source, python_extractor)
        imports = python_extractor.extract_imports(tree, src, "/my/module.py")
        assert all(imp.source_file == "/my/module.py" for imp in imports)

    def test_multiple_imports(self, python_extractor):
        """Extract multiple import statements."""
        source = "import os\nimport sys\nimport json\n"
        tree, src = _parse_python(source, python_extractor)
        imports = python_extractor.extract_imports(tree, src, "/test.py")
        assert len(imports) >= 3
        modules = {imp.module_path for imp in imports}
        assert "os" in modules
        assert "sys" in modules
        assert "json" in modules

    def test_import_with_scope(self, python_extractor):
        """Import carries scope_id and source_channel."""
        source = "import os\n"
        tree, src = _parse_python(source, python_extractor)
        imports = python_extractor.extract_imports(
            tree, src, "/test.py", scope_id="s1", source_channel="cli",
        )
        assert imports[0].scope_id == "s1"
        assert imports[0].source_channel == "cli"

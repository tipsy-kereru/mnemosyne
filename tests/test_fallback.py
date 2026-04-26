"""
Tests for TreeSitterExtractor refactoring and regex fallback (SPEC-TS-001 Task 6).

Covers: dispatching to language extractors, regex fallback for unavailable
grammars, extraction_method tagging, and backward compatibility.
"""

import tempfile
from pathlib import Path

import pytest

from mnemosyne.extraction.deterministic.code_parser import CodeEntity, TreeSitterExtractor


class TestExtractionMethod:
    """Tests for extraction_method tagging."""

    def test_python_file_uses_tree_sitter_when_grammar_available(self):
        """Python files use tree-sitter extraction when grammar is loaded."""
        ext = TreeSitterExtractor()
        if "python" not in ext._grammars:
            pytest.skip("tree-sitter-python not installed")

        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def hello():\n    pass\n")
            f.flush()
            entities = ext.extract_file(Path(f.name))
            assert len(entities) >= 1
            assert entities[0].properties.get("extraction_method") == "tree-sitter"

    def test_unavailable_language_uses_regex_fallback(self):
        """Languages without grammar packages fall back to regex extraction."""
        ext = TreeSitterExtractor()
        # Find a language whose grammar is unavailable
        fallback_lang = None
        for ext_name, lang_name in TreeSitterExtractor.SUPPORTED_LANGUAGES.items():
            if lang_name not in ext._grammars:
                fallback_lang = ext_name
                break

        if fallback_lang is None:
            pytest.skip("All grammars available, cannot test fallback")

        with tempfile.NamedTemporaryFile(suffix=fallback_lang, mode="w", delete=False) as f:
            # Write some code that the regex parser would catch
            if fallback_lang in (".go",):
                f.write('package main\n\nfunc main() {\n}\n')
            elif fallback_lang in (".rs",):
                f.write("fn main() {}\n")
            elif fallback_lang in (".js", ".ts", ".tsx", ".jsx"):
                f.write("function hello() {}\n")
            else:
                f.write("function test() {}\n")
            f.flush()
            entities = ext.extract_file(Path(f.name))
            # If entities found, they should have extraction_method=regex
            for entity in entities:
                assert entity.properties.get("extraction_method") == "regex"


class TestExtractFileFull:
    """Tests for extract_file_full returning ParseResult."""

    def test_extract_file_full_returns_parse_result(self):
        """extract_file_full returns a ParseResult with entities, imports, calls."""
        from mnemosyne.extraction.deterministic.types import ParseResult

        ext = TreeSitterExtractor()
        if "python" not in ext._grammars:
            pytest.skip("tree-sitter-python not installed")

        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("import os\n\ndef hello():\n    os.path.join('a', 'b')\n")
            f.flush()
            result = ext.extract_file_full(Path(f.name))
            assert isinstance(result, ParseResult)
            assert len(result.entities) >= 1
            assert result.extraction_method == "tree-sitter"
            assert result.language == "python"
            assert result.content_hash != ""

    def test_extract_file_full_contains_imports(self):
        """extract_file_full includes import declarations."""
        ext = TreeSitterExtractor()
        if "python" not in ext._grammars:
            pytest.skip("tree-sitter-python not installed")

        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("import os\nimport sys\n\ndef hello():\n    pass\n")
            f.flush()
            result = ext.extract_file_full(Path(f.name))
            assert len(result.imports) >= 2

    def test_extract_file_full_contains_calls(self):
        """extract_file_full includes call-graph edges."""
        ext = TreeSitterExtractor()
        if "python" not in ext._grammars:
            pytest.skip("tree-sitter-python not installed")

        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def foo():\n    bar()\n")
            f.flush()
            result = ext.extract_file_full(Path(f.name))
            assert len(result.calls) >= 1


class TestBackwardCompatibility:
    """Tests ensuring existing API continues to work."""

    def test_extract_file_returns_list_of_code_entity(self):
        """extract_file() still returns List[CodeEntity]."""
        ext = TreeSitterExtractor()
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def hello():\n    pass\n")
            f.flush()
            entities = ext.extract_file(Path(f.name))
            assert isinstance(entities, list)
            assert all(isinstance(e, CodeEntity) for e in entities)

    def test_extract_directory_returns_list_of_code_entity(self):
        """extract_directory() still returns List[CodeEntity]."""
        ext = TreeSitterExtractor()
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir) / "test.py"
            py_file.write_text("def hello():\n    pass\n")
            entities = ext.extract_directory(Path(tmpdir))
            assert isinstance(entities, list)
            assert len(entities) >= 1

    def test_to_wiki_format_still_works(self):
        """to_wiki_format(entities) still produces markdown."""
        ext = TreeSitterExtractor()
        entities = [
            CodeEntity(
                type="function",
                name="my_func",
                language="python",
                file_path="/test.py",
                line_start=1,
                line_end=5,
                properties={"parameters": "x, y"},
            )
        ]
        wiki = ext.to_wiki_format(entities)
        assert "my_func" in wiki
        assert "python" in wiki

    def test_entities_attribute_accumulates(self):
        """The entities attribute still accumulates across extract_file calls."""
        ext = TreeSitterExtractor()
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                py_file = Path(tmpdir) / f"file{i}.py"
                py_file.write_text(f"def func_{i}():\n    pass\n")
                ext.extract_file(py_file)
            assert len(ext.entities) >= 3

    def test_scope_id_passed_through(self):
        """scope_id and source_channel are passed to entities."""
        ext = TreeSitterExtractor()
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def hello():\n    pass\n")
            f.flush()
            entities = ext.extract_file(
                Path(f.name), scope_id="session-1", source_channel="cli",
            )
            assert all(e.scope_id == "session-1" for e in entities)
            assert all(e.source_channel == "cli" for e in entities)

"""
Tests for wiki format generation with import/call graph sections (SPEC-TS-001 Task 8).

Covers: wiki-links format, Import/Call Graph sections, backward compatibility,
scope-qualified links.
"""

import pytest

from mnemosyne.extraction.deterministic.code_parser import CodeEntity, TreeSitterExtractor
from mnemosyne.extraction.deterministic.types import CallRelation, ImportEntity


class TestWikiFormatWithGraphs:
    """Tests for to_wiki_format with import and call graph sections."""

    @pytest.fixture
    def extractor(self):
        return TreeSitterExtractor()

    def test_wiki_links_entity_format(self, extractor):
        """Wiki output uses [[entity_type:name]] link format."""
        entities = [
            CodeEntity(
                type="function",
                name="my_func",
                language="python",
                file_path="/test.py",
                line_start=1,
                line_end=5,
                properties={},
            )
        ]
        wiki = extractor.to_wiki_format(entities)
        assert "[[python:my_func]]" in wiki

    def test_wiki_import_graph_section(self, extractor):
        """to_wiki_format generates Import Graph section when imports provided."""
        entities = [
            CodeEntity(
                type="function",
                name="my_func",
                language="python",
                file_path="/test.py",
                line_start=1,
                line_end=5,
                properties={},
            )
        ]
        imports = [
            ImportEntity(
                source_file="/test.py",
                module_path="os",
                imported_names=["os"],
                is_local=False,
                line_number=1,
            )
        ]
        wiki = extractor.to_wiki_format(entities, imports=imports)
        assert "Import Graph" in wiki

    def test_wiki_call_graph_section(self, extractor):
        """to_wiki_format generates Call Graph section when calls provided."""
        entities = [
            CodeEntity(
                type="function",
                name="foo",
                language="python",
                file_path="/test.py",
                line_start=1,
                line_end=3,
                properties={},
            ),
            CodeEntity(
                type="function",
                name="bar",
                language="python",
                file_path="/test.py",
                line_start=5,
                line_end=7,
                properties={},
            ),
        ]
        calls = [
            CallRelation(
                caller_name="foo",
                caller_file="/test.py",
                callee_name="bar",
                callee_line=2,
                call_type="function_call",
            )
        ]
        wiki = extractor.to_wiki_format(entities, calls=calls)
        assert "Call Graph" in wiki

    def test_backward_compat_entities_only(self, extractor):
        """to_wiki_format(entities) still works without imports/calls."""
        entities = [
            CodeEntity(
                type="function",
                name="hello",
                language="python",
                file_path="/test.py",
                line_start=1,
                line_end=3,
                properties={},
            )
        ]
        wiki = extractor.to_wiki_format(entities)
        assert "hello" in wiki
        assert "python" in wiki

    def test_no_import_graph_when_empty(self, extractor):
        """No Import Graph section when imports list is empty or None."""
        entities = [
            CodeEntity(
                type="function",
                name="f",
                language="python",
                file_path="/test.py",
                line_start=1,
                line_end=1,
                properties={},
            )
        ]
        wiki = extractor.to_wiki_format(entities, imports=[])
        assert "Import Graph" not in wiki

    def test_no_call_graph_when_empty(self, extractor):
        """No Call Graph section when calls list is empty or None."""
        entities = [
            CodeEntity(
                type="function",
                name="f",
                language="python",
                file_path="/test.py",
                line_start=1,
                line_end=1,
                properties={},
            )
        ]
        wiki = extractor.to_wiki_format(entities, calls=[])
        assert "Call Graph" not in wiki

    def test_scope_qualified_links(self, extractor):
        """Entities with scope_id produce scope-qualified wiki links."""
        entities = [
            CodeEntity(
                type="function",
                name="f",
                language="python",
                file_path="/test.py",
                line_start=1,
                line_end=1,
                properties={},
                scope_id="session-42",
            )
        ]
        wiki = extractor.to_wiki_format(entities)
        assert "session-42" in wiki


class TestCLIIntegration:
    """Tests for CLI integration with new extraction pipeline."""

    def test_cli_imports(self):
        """CLI module imports successfully."""
        from mnemosyne.extraction import cli
        assert hasattr(cli, "main")

    def test_cli_help_runs(self):
        """CLI --help does not error."""
        from mnemosyne.extraction.cli import main
        # Should not raise
        try:
            main(["--help"])
        except SystemExit as e:
            assert e.code == 0

"""
Tests for TreeSitterExtractor grammar loading and API validation (SPEC-TS-001 Task 2).

Covers: grammar initialization, _grammars dict, _unavailable_languages set,
idempotent loading, and parser creation.
"""

import pytest


class TestGrammarLoading:
    """Tests for TreeSitterExtractor grammar initialization."""

    def test_init_creates_grammars_dict(self):
        """TreeSitterExtractor.__init__() creates a _grammars dict."""
        from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor

        ext = TreeSitterExtractor()
        assert hasattr(ext, "_grammars")
        assert isinstance(ext._grammars, dict)

    def test_init_creates_unavailable_languages_set(self):
        """TreeSitterExtractor.__init__() creates _unavailable_languages set."""
        from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor

        ext = TreeSitterExtractor()
        assert hasattr(ext, "_unavailable_languages")
        assert isinstance(ext._unavailable_languages, set)

    def test_python_grammar_loaded_when_available(self):
        """When tree-sitter-python is installed, 'python' is in _grammars."""
        from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor

        ext = TreeSitterExtractor()
        # tree-sitter-python is installed in this environment
        assert "python" in ext._grammars

    def test_python_grammar_is_language_object(self):
        """Loaded grammar values are tree_sitter.Language instances."""
        from tree_sitter import Language

        from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor

        ext = TreeSitterExtractor()
        if "python" in ext._grammars:
            assert isinstance(ext._grammars["python"], Language)

    def test_unavailable_languages_not_in_grammars(self):
        """Languages without grammar packages are in _unavailable_languages."""
        from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor

        ext = TreeSitterExtractor()
        # A language without its grammar package installed should be unavailable
        # and NOT in _grammars
        for lang in ext._unavailable_languages:
            assert lang not in ext._grammars

    def test_grammar_loading_is_idempotent(self):
        """Creating two TreeSitterExtractor instances loads same grammars."""
        from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor

        ext1 = TreeSitterExtractor()
        ext2 = TreeSitterExtractor()
        assert set(ext1._grammars.keys()) == set(ext2._grammars.keys())
        assert ext1._unavailable_languages == ext2._unavailable_languages

    def test_parser_creation_for_available_language(self):
        """Can create a parser for an available language."""
        from tree_sitter import Parser

        from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor

        ext = TreeSitterExtractor()
        if "python" in ext._grammars:
            parser = Parser(ext._grammars["python"])
            assert parser is not None
            tree = parser.parse(b"def f(): pass")
            assert tree.root_node.type == "module"

    def test_no_unavailable_language_in_grammars_keys(self):
        """_grammars and _unavailable_languages are disjoint sets."""
        from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor

        ext = TreeSitterExtractor()
        overlap = set(ext._grammars.keys()) & ext._unavailable_languages
        assert overlap == set()

    def test_expected_language_keys_attempted(self):
        """The extractor attempts to load the 6 expected languages."""
        from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor

        ext = TreeSitterExtractor()
        expected = {"python", "javascript", "typescript", "tsx", "go", "rust"}
        all_attempted = set(ext._grammars.keys()) | ext._unavailable_languages
        assert expected.issubset(all_attempted)

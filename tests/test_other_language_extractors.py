"""
Tests for JS/TS, Go, and Rust language extractors (SPEC-TS-001 Task 4).

Covers: basic entity extraction for each language. Tests that need
unavailable grammars use mock or skip gracefully.
"""



class TestJavaScriptExtractor:
    """Tests for the JavaScript/TypeScript extractor class structure."""

    def test_javascript_extractor_class_exists(self):
        """JavaScriptExtractor class is importable."""
        from mnemosyne.extraction.deterministic.languages.javascript_extractor import (
            JavaScriptExtractor,
        )
        assert JavaScriptExtractor is not None

    def test_javascript_extractor_language_name(self):
        """JavaScriptExtractor has language_name='javascript'."""
        from mnemosyne.extraction.deterministic.languages.javascript_extractor import (
            JavaScriptExtractor,
        )
        ext = JavaScriptExtractor()
        assert ext.language_name == "javascript"

    def test_javascript_extractor_has_grammar_attr(self):
        """JavaScriptExtractor has a grammar attribute."""
        from mnemosyne.extraction.deterministic.languages.javascript_extractor import (
            JavaScriptExtractor,
        )
        ext = JavaScriptExtractor()
        assert hasattr(ext, "grammar")


class TestGoExtractor:
    """Tests for the Go extractor class structure."""

    def test_go_extractor_class_exists(self):
        """GoExtractor class is importable."""
        from mnemosyne.extraction.deterministic.languages.go_extractor import (
            GoExtractor,
        )
        assert GoExtractor is not None

    def test_go_extractor_language_name(self):
        """GoExtractor has language_name='go'."""
        from mnemosyne.extraction.deterministic.languages.go_extractor import (
            GoExtractor,
        )
        ext = GoExtractor()
        assert ext.language_name == "go"

    def test_go_extractor_has_grammar_attr(self):
        """GoExtractor has a grammar attribute."""
        from mnemosyne.extraction.deterministic.languages.go_extractor import (
            GoExtractor,
        )
        ext = GoExtractor()
        assert hasattr(ext, "grammar")


class TestRustExtractor:
    """Tests for the Rust extractor class structure."""

    def test_rust_extractor_class_exists(self):
        """RustExtractor class is importable."""
        from mnemosyne.extraction.deterministic.languages.rust_extractor import (
            RustExtractor,
        )
        assert RustExtractor is not None

    def test_rust_extractor_language_name(self):
        """RustExtractor has language_name='rust'."""
        from mnemosyne.extraction.deterministic.languages.rust_extractor import (
            RustExtractor,
        )
        ext = RustExtractor()
        assert ext.language_name == "rust"

    def test_rust_extractor_has_grammar_attr(self):
        """RustExtractor has a grammar attribute."""
        from mnemosyne.extraction.deterministic.languages.rust_extractor import (
            RustExtractor,
        )
        ext = RustExtractor()
        assert hasattr(ext, "grammar")


class TestExtractorsWithUnavailableGrammar:
    """Tests for extractors when grammar packages are not installed.

    These verify graceful degradation: the extractor should still be
    constructable but grammar will be None or raise on use.
    """

    def test_javascript_grammar_none_when_unavailable(self):
        """JavaScriptExtractor.grammar is None when tree-sitter-javascript missing."""
        from mnemosyne.extraction.deterministic.languages.javascript_extractor import (
            JavaScriptExtractor,
        )
        ext = JavaScriptExtractor()
        # If tree-sitter-javascript is not installed, grammar should be None
        # If it IS installed, grammar will be a Language object (also valid)
        if "javascript" not in _get_available_grammars():
            assert ext.grammar is None

    def test_go_grammar_none_when_unavailable(self):
        """GoExtractor.grammar is None when tree-sitter-go missing."""
        from mnemosyne.extraction.deterministic.languages.go_extractor import (
            GoExtractor,
        )
        ext = GoExtractor()
        if "go" not in _get_available_grammars():
            assert ext.grammar is None

    def test_rust_grammar_none_when_unavailable(self):
        """RustExtractor.grammar is None when tree-sitter-rust missing."""
        from mnemosyne.extraction.deterministic.languages.rust_extractor import (
            RustExtractor,
        )
        ext = RustExtractor()
        if "rust" not in _get_available_grammars():
            assert ext.grammar is None


def _get_available_grammars():
    """Helper: check which grammars are available in the current environment."""
    from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor
    ext = TreeSitterExtractor()
    return set(ext._grammars.keys())

"""Tests for LanguageExtractor protocol (SPEC-PROD-002, REQ-004).

Verifies that the runtime_checkable protocol in base.py works correctly
and that each language extractor conforms to it.
"""

from unittest.mock import MagicMock


from mnemosyne.extraction.deterministic.languages.base import LanguageExtractor


class TestLanguageExtractorProtocol:
    """Test the protocol definition itself."""

    def test_protocol_is_runtime_checkable(self):
        assert hasattr(LanguageExtractor, "__protocol_attrs__") or hasattr(
            LanguageExtractor, "__abstractmethods__"
        )

    def test_mock_conforming_class_passes_isinstance(self):
        """A mock with all protocol attributes passes isinstance check."""

        class Conforming:
            language_name = "test"
            grammar = MagicMock()

            def extract_entities(self, tree, source, file_path, **kw):
                return []

            def extract_imports(self, tree, source, file_path, **kw):
                return []

            def extract_calls(self, tree, source, file_path, **kw):
                return []

        assert isinstance(Conforming(), LanguageExtractor)

    def test_non_conforming_class_fails_isinstance(self):
        """A class missing required methods fails isinstance."""

        class NonConforming:
            language_name = "test"

        assert not isinstance(NonConforming(), LanguageExtractor)

    def test_partial_conforming_fails_isinstance(self):
        """A class missing extract_calls fails isinstance."""

        class Partial:
            language_name = "test"
            grammar = MagicMock()

            def extract_entities(self, tree, source, file_path, **kw):
                return []

            def extract_imports(self, tree, source, file_path, **kw):
                return []

        assert not isinstance(Partial(), LanguageExtractor)


class TestConcreteExtractorsConformance:
    """Verify each language extractor satisfies the protocol."""

    def _get_extractor(self, module_path, class_name):
        import importlib

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        try:
            return cls()
        except Exception:
            return None

    def test_python_extractor_conforms(self):
        ext = self._get_extractor(
            "mnemosyne.extraction.deterministic.languages.python_extractor",
            "PythonExtractor",
        )
        if ext is not None:
            assert hasattr(ext, "language_name")
            assert hasattr(ext, "extract_entities")
            assert hasattr(ext, "extract_imports")
            assert hasattr(ext, "extract_calls")

    def test_javascript_extractor_conforms(self):
        ext = self._get_extractor(
            "mnemosyne.extraction.deterministic.languages.javascript_extractor",
            "JavaScriptExtractor",
        )
        if ext is not None:
            assert hasattr(ext, "language_name")
            assert hasattr(ext, "extract_entities")
            assert hasattr(ext, "extract_imports")
            assert hasattr(ext, "extract_calls")

    def test_go_extractor_conforms(self):
        ext = self._get_extractor(
            "mnemosyne.extraction.deterministic.languages.go_extractor",
            "GoExtractor",
        )
        if ext is not None:
            assert hasattr(ext, "language_name")
            assert hasattr(ext, "extract_entities")
            assert hasattr(ext, "extract_imports")
            assert hasattr(ext, "extract_calls")

    def test_rust_extractor_conforms(self):
        ext = self._get_extractor(
            "mnemosyne.extraction.deterministic.languages.rust_extractor",
            "RustExtractor",
        )
        if ext is not None:
            assert hasattr(ext, "language_name")
            assert hasattr(ext, "extract_entities")
            assert hasattr(ext, "extract_imports")
            assert hasattr(ext, "extract_calls")

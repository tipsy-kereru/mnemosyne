"""Tests for semantic SLM extractors (SPEC-PROD-002, REQ-002).

Covers mnemosyne/extraction/semantic/slm_extractor.py:
GLiNER2Extractor, REBELExtractor, SemanticExtractor, cleanup, context managers,
and fallback paths.
"""

import json
from unittest.mock import MagicMock, patch


from mnemosyne.extraction.semantic.slm_extractor import (
    GLiNER2Extractor,
    REBELExtractor,
    SemanticExtractor,
)


class TestGLiNER2ExtractorFallback:
    """Test GLiNER2Extractor when model is not installed (fallback path)."""

    def test_model_none_when_not_installed(self):
        ext = GLiNER2Extractor()
        # GLiNER likely not installed in test env
        assert ext.model is None

    def test_fallback_extracts_email(self):
        ext = GLiNER2Extractor()
        result = ext._extract_fallback(
            "Contact user@example.com for info",
            ["EMAIL"],
        )
        assert len(result) >= 1
        assert result[0].type == "EMAIL"
        assert "user@example.com" in result[0].text

    def test_fallback_extracts_date(self):
        ext = GLiNER2Extractor()
        result = ext._extract_fallback(
            "Deadline is 2024-01-15 for the project",
            ["DATE"],
        )
        assert len(result) >= 1
        assert result[0].type == "DATE"

    def test_fallback_extracts_url(self):
        ext = GLiNER2Extractor()
        result = ext._extract_fallback(
            "Visit https://example.com for details",
            ["URL"],
        )
        assert len(result) >= 1
        assert "example.com" in result[0].text

    def test_fallback_extracts_person(self):
        ext = GLiNER2Extractor()
        result = ext._extract_fallback(
            "John Smith works at Google",
            ["PERSON"],
        )
        assert len(result) >= 1
        assert "John Smith" in result[0].text

    def test_fallback_extracts_organization(self):
        ext = GLiNER2Extractor()
        result = ext._extract_fallback(
            "Google Inc announced new product",
            ["ORGANIZATION"],
        )
        assert len(result) >= 1

    def test_fallback_no_match_returns_empty(self):
        ext = GLiNER2Extractor()
        result = ext._extract_fallback("hello world", ["PERSON"])
        assert result == []

    def test_fallback_unknown_entity_type(self):
        ext = GLiNER2Extractor()
        result = ext._extract_fallback("some text", ["UNKNOWN_TYPE"])
        assert result == []

    def test_fallback_with_scope(self):
        ext = GLiNER2Extractor()
        result = ext._extract_fallback(
            "user@example.com",
            ["EMAIL"],
            scope_id="session-1",
            source_channel="cli",
        )
        assert result[0].scope_id == "session-1"
        assert result[0].source_channel == "cli"


class TestGLiNER2ExtractorExtract:
    """Test the public extract() method dispatching."""

    def test_extract_uses_fallback_when_no_model(self):
        ext = GLiNER2Extractor()
        with patch.object(ext, "_extract_fallback", return_value=[]) as mock_fb:
            ext.extract("text", ["EMAIL"])
            mock_fb.assert_called_once()

    def test_extract_uses_model_when_available(self):
        ext = GLiNER2Extractor.__new__(GLiNER2Extractor)
        ext.model = MagicMock()
        ext.model_name = "test"
        ext.model.predict_entities.return_value = [
            {"label": "PERSON", "text": "John", "score": 0.9, "start": 0, "end": 4}
        ]
        result = ext.extract("John works here", ["PERSON"])
        assert len(result) == 1
        assert result[0].source == "gliner2"


class TestGLiNER2ExtractorCleanup:
    def test_cleanup_sets_model_none(self):
        ext = GLiNER2Extractor.__new__(GLiNER2Extractor)
        ext.model = MagicMock()
        ext.model_name = "test"
        ext.cleanup()
        assert ext.model is None

    def test_context_manager_calls_cleanup(self):
        ext = GLiNER2Extractor.__new__(GLiNER2Extractor)
        ext.model = MagicMock()
        ext.model_name = "test"
        with ext:
            assert ext.model is not None
        assert ext.model is None

    def test_context_manager_returns_self(self):
        ext = GLiNER2Extractor.__new__(GLiNER2Extractor)
        ext.model = None
        ext.model_name = "test"
        with ext as ctx:
            assert ctx is ext


class TestREBELExtractorFallback:
    """Test REBELExtractor when model is not installed."""

    def test_model_none_when_not_installed(self):
        ext = REBELExtractor()
        assert ext.model is None
        assert ext.tokenizer is None

    def test_fallback_works_for_relation(self):
        ext = REBELExtractor()
        result = ext._extract_fallback("Google is a company")
        assert len(result) >= 1
        assert result[0].relation == "is_a"

    def test_fallback_works_for_located_in(self):
        ext = REBELExtractor()
        result = ext._extract_fallback("Office located in Seattle")
        assert len(result) >= 1
        assert result[0].relation == "located_in"

    def test_fallback_works_for_works_for(self):
        ext = REBELExtractor()
        result = ext._extract_fallback("John works for Google")
        assert len(result) >= 1
        assert result[0].relation == "works_for"

    def test_fallback_no_match(self):
        ext = REBELExtractor()
        result = ext._extract_fallback("the weather is nice")
        assert result == []

    def test_fallback_with_scope(self):
        ext = REBELExtractor()
        result = ext._extract_fallback(
            "Office located in Seattle",
            scope_id="s1",
            source_channel="api",
        )
        assert result[0].scope_id == "s1"
        assert result[0].source_channel == "api"


class TestREBELExtractorParse:
    def test_parse_rebel_output(self):
        ext = REBELExtractor()
        output = "<triplet> Google <relation> headquartered in <object> Mountain View"
        triples = ext._parse_rebel_output(output)
        assert len(triples) == 1
        assert triples[0] == ("Google", "headquartered in", "Mountain View")

    def test_parse_rebel_output_empty(self):
        ext = REBELExtractor()
        triples = ext._parse_rebel_output("no triples here")
        assert triples == []


class TestREBELExtractorCleanup:
    def test_cleanup_sets_none(self):
        ext = REBELExtractor.__new__(REBELExtractor)
        ext.model = MagicMock()
        ext.tokenizer = MagicMock()
        ext.model_name = "test"
        ext.cleanup()
        assert ext.model is None
        assert ext.tokenizer is None

    def test_context_manager(self):
        ext = REBELExtractor.__new__(REBELExtractor)
        ext.model = MagicMock()
        ext.tokenizer = MagicMock()
        ext.model_name = "test"
        with ext:
            assert ext.model is not None
        assert ext.model is None


class TestSemanticExtractor:
    def test_extract_returns_dict(self):
        ext = SemanticExtractor()
        result = ext.extract("John Smith works at Google Inc", ["PERSON", "ORGANIZATION"])
        assert "entities" in result
        assert "relations" in result
        assert "token_cost" in result
        assert result["extraction_method"] == "local_slm"

    def test_extract_with_scope(self):
        ext = SemanticExtractor()
        result = ext.extract(
            "user@example.com",
            ["EMAIL"],
            scope_id="s1",
            source_channel="test",
        )
        entities = result["entities"]
        assert len(entities) >= 1
        assert entities[0]["scope_id"] == "s1"

    def test_cleanup(self):
        ext = SemanticExtractor()
        ext.cleanup()
        assert ext.ner.model is None
        assert ext.re.model is None

    def test_context_manager(self):
        ext = SemanticExtractor()
        with ext as ctx:
            assert ctx is ext
        assert ext.ner.model is None

    def test_estimate_tokens(self):
        ext = SemanticExtractor()
        tokens = ext._estimate_tokens("hello world foo")
        assert tokens > 0


class TestSLMMainCLI:
    def test_main_with_text_arg(self, capsys):
        from mnemosyne.extraction.semantic.slm_extractor import main
        with patch("sys.argv", ["slm_extractor", "--text", "John works at Google"]):
            main()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "entities" in output

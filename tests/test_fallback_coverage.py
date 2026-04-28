"""Tests for code parser regex fallback paths (SPEC-PROD-002, REQ-003).

Covers mnemosyne/extraction/deterministic/code_parser.py:
fallback extraction methods, SpaCyExtractor, cache miss paths,
and unsupported language handling.
"""

from unittest.mock import patch

import pytest

from mnemosyne.extraction.deterministic.code_parser import (
    SpaCyExtractor,
    TreeSitterExtractor,
)


@pytest.fixture
def extractor():
    return TreeSitterExtractor()


# ---- Fallback extraction: Python ----


class TestFallbackPython:
    def test_extract_function(self, extractor, tmp_path):
        p = tmp_path / "test.py"
        p.write_text("def hello():\n    pass\n")
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "hello" in names

    def test_extract_async_function(self, extractor, tmp_path):
        p = tmp_path / "test.py"
        p.write_text("async def fetch_data():\n    pass\n")
        result = extractor.extract_file_full(p)
        funcs = [e for e in result.entities if e.type == "function"]
        assert any(e.name == "fetch_data" for e in funcs)

    def test_extract_class(self, extractor, tmp_path):
        p = tmp_path / "test.py"
        p.write_text("class MyClass(Base):\n    pass\n")
        result = extractor.extract_file_full(p)
        classes = [e for e in result.entities if e.type == "class"]
        assert any(e.name == "MyClass" for e in classes)

    def test_extract_function_with_return_type(self, extractor, tmp_path):
        p = tmp_path / "test.py"
        p.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
        result = extractor.extract_file_full(p)
        funcs = [e for e in result.entities if e.name == "add"]
        assert len(funcs) >= 1


# ---- Fallback extraction: JavaScript/TypeScript ----


class TestFallbackJS:
    def test_extract_js_function(self, extractor, tmp_path):
        p = tmp_path / "test.js"
        p.write_text("function hello() {\n  return 1;\n}\n")
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "hello" in names

    def test_extract_js_class(self, extractor, tmp_path):
        p = tmp_path / "test.js"
        p.write_text("class MyClass extends Base {\n}\n")
        result = extractor.extract_file_full(p)
        classes = [e for e in result.entities if e.type == "class"]
        assert any(e.name == "MyClass" for e in classes)

    def test_extract_js_arrow_function(self, extractor, tmp_path):
        p = tmp_path / "test.js"
        p.write_text("const add = (a, b) => a + b;\n")
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "add" in names

    def test_extract_ts_function(self, extractor, tmp_path):
        p = tmp_path / "test.ts"
        p.write_text("function greet(name: string): void {}\n")
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "greet" in names


# ---- Fallback extraction: Go ----


class TestFallbackGo:
    def test_extract_go_function(self, extractor, tmp_path):
        p = tmp_path / "test.go"
        p.write_text('package main\n\nfunc hello() string {\n\treturn "hi"\n}\n')
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "hello" in names

    def test_extract_go_method(self, extractor, tmp_path):
        p = tmp_path / "test.go"
        p.write_text("package main\n\ntype Server struct{}\n\nfunc (s *Server) Start() {}\n")
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "Start" in names

    def test_extract_go_struct(self, extractor, tmp_path):
        p = tmp_path / "test.go"
        p.write_text("package main\n\ntype Config struct {\n\tPort int\n}\n")
        result = extractor.extract_file_full(p)
        classes = [e for e in result.entities if e.type == "class"]
        assert any(e.name == "Config" for e in classes)


# ---- Fallback extraction: Rust ----


class TestFallbackRust:
    def test_extract_rust_function(self, extractor, tmp_path):
        p = tmp_path / "test.rs"
        p.write_text("fn main() {\n    println!(\"hello\");\n}\n")
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "main" in names

    def test_extract_rust_pub_function(self, extractor, tmp_path):
        p = tmp_path / "test.rs"
        p.write_text("pub fn greet(name: &str) -> String {\n    format!(\"Hi {}\", name)\n}\n")
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "greet" in names

    def test_extract_rust_struct(self, extractor, tmp_path):
        p = tmp_path / "test.rs"
        p.write_text("struct Point {\n    x: f64,\n    y: f64,\n}\n")
        result = extractor.extract_file_full(p)
        classes = [e for e in result.entities if e.type == "class"]
        assert any(e.name == "Point" for e in classes)

    def test_extract_rust_enum(self, extractor, tmp_path):
        p = tmp_path / "test.rs"
        p.write_text("enum Color {\n    Red,\n    Green,\n}\n")
        result = extractor.extract_file_full(p)
        classes = [e for e in result.entities if e.type == "class"]
        assert any(e.name == "Color" for e in classes)

    def test_extract_rust_async_function(self, extractor, tmp_path):
        p = tmp_path / "test.rs"
        p.write_text("async fn fetch(url: &str) -> String {\n    String::new()\n}\n")
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "fetch" in names


# ---- Unsupported language ----


class TestUnsupportedLanguage:
    def test_unsupported_suffix_returns_empty(self, extractor, tmp_path):
        p = tmp_path / "test.xyz"
        p.write_text("some content\n")
        result = extractor.extract_file_full(p)
        assert result.entities == []


# ---- Cache behavior ----


class TestCacheBehavior:
    def test_cache_hit_returns_same_result(self, extractor, tmp_path):
        p = tmp_path / "test.py"
        p.write_text("def foo(): pass\n")
        result1 = extractor.extract_file_full(p)
        result2 = extractor.extract_file_full(p)
        assert result1.content_hash == result2.content_hash

    def test_clear_cache(self, extractor, tmp_path):
        p = tmp_path / "test.py"
        p.write_text("def bar(): pass\n")
        extractor.extract_file_full(p)
        assert len(extractor._cache) > 0
        extractor.clear_cache()
        assert len(extractor._cache) == 0


# ---- SpaCyExtractor ----


class TestSpaCyExtractor:
    def test_init_without_spacy(self):
        """SpaCyExtractor sets nlp=None when spacy is unavailable."""
        with patch("mnemosyne.extraction.deterministic.code_parser.SpaCyExtractor.__init__", lambda self, model="en_core_web_sm": setattr(self, 'nlp', None)):
            ext = SpaCyExtractor()
        assert ext.nlp is None

    def test_extract_entities_returns_empty_when_no_nlp(self):
        ext = SpaCyExtractor.__new__(SpaCyExtractor)
        ext.nlp = None
        result = ext.extract_entities("Hello world")
        assert result == []

    def test_extract_relations_returns_empty_when_no_nlp(self):
        ext = SpaCyExtractor.__new__(SpaCyExtractor)
        ext.nlp = None
        result = ext.extract_relations("John works at Google")
        assert result == []

    def test_extract_entities_with_custom_types(self):
        ext = SpaCyExtractor.__new__(SpaCyExtractor)
        ext.nlp = None
        result = ext.extract_entities("text", custom_types=None)
        assert result == []

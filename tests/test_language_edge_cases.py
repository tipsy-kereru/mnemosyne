"""Tests for language-specific edge cases (SPEC-PROD-002, REQ-007).

Targets regex fallback paths for JS/TS, Go, and Rust extractors
via TreeSitterExtractor when grammars are not available.
"""

import textwrap

import pytest

from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor


@pytest.fixture
def extractor():
    return TreeSitterExtractor()


# ---- JavaScript/TypeScript edge cases ----


class TestJSEdgeCases:
    def test_async_arrow_function(self, extractor, tmp_path):
        p = tmp_path / "test.js"
        p.write_text("const fetch = async (url) => {\n  return await fetch(url);\n};\n")
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "fetch" in names

    def test_jsx_component(self, extractor, tmp_path):
        p = tmp_path / "component.jsx"
        p.write_text("class App extends React.Component {\n  render() { return null; }\n}\n")
        result = extractor.extract_file_full(p)
        classes = [e for e in result.entities if e.type == "class"]
        assert any(e.name == "App" for e in classes)

    def test_async_function_declaration(self, extractor, tmp_path):
        p = tmp_path / "test.js"
        p.write_text("async function loadData() {\n  return [];\n}\n")
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "loadData" in names

    def test_var_function_assignment(self, extractor, tmp_path):
        """var keyword is not in the regex pattern — verify no crash."""
        p = tmp_path / "test.js"
        p.write_text("var handler = (event) => {\n  console.log(event);\n};\n")
        result = extractor.extract_file_full(p)
        assert result.entities is not None

    def test_empty_js_file(self, extractor, tmp_path):
        p = tmp_path / "empty.js"
        p.write_text("")
        result = extractor.extract_file_full(p)
        assert result.entities == []

    def test_nested_jsx_file(self, extractor, tmp_path):
        """tsx files should use tsx language mapping."""
        p = tmp_path / "app.tsx"
        p.write_text("function App() {\n  return null;\n}\n")
        result = extractor.extract_file_full(p)
        # Should not crash regardless of extraction method
        assert result.entities is not None


class TestGoEdgeCases:
    def test_interface_method(self, extractor, tmp_path):
        p = tmp_path / "test.go"
        p.write_text(textwrap.dedent("""\
            package main

            type Handler interface {
                ServeHTTP()
            }
        """))
        result = extractor.extract_file_full(p)
        # interface is not a struct, may or may not be extracted
        assert result.entities is not None

    def test_blank_import(self, extractor, tmp_path):
        p = tmp_path / "test.go"
        p.write_text(textwrap.dedent("""\
            package main

            import _ "embed"

            func main() {}
        """))
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "main" in names

    def test_multiple_return_values(self, extractor, tmp_path):
        p = tmp_path / "test.go"
        p.write_text(textwrap.dedent("""\
            package main

            func divide(a, b int) (int, error) {
                return a / b, nil
            }
        """))
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "divide" in names

    def test_empty_go_file(self, extractor, tmp_path):
        p = tmp_path / "empty.go"
        p.write_text("package main\n")
        result = extractor.extract_file_full(p)
        assert result.entities == []


class TestRustEdgeCases:
    def test_trait_implementation(self, extractor, tmp_path):
        p = tmp_path / "test.rs"
        p.write_text(textwrap.dedent("""\
            struct Point { x: i32, y: i32 }

            impl Display for Point {
                fn fmt(&self) {}
            }
        """))
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "fmt" in names

    def test_use_grouping(self, extractor, tmp_path):
        p = tmp_path / "test.rs"
        p.write_text(textwrap.dedent("""\
            use std::collections::{HashMap, BTreeMap};

            fn create_map() -> HashMap<String, i32> {
                HashMap::new()
            }
        """))
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "create_map" in names

    def test_macro_call(self, extractor, tmp_path):
        p = tmp_path / "test.rs"
        p.write_text(textwrap.dedent("""\
            fn main() {
                println!("Hello");
                vec![1, 2, 3];
            }
        """))
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "main" in names

    def test_generic_function(self, extractor, tmp_path):
        p = tmp_path / "test.rs"
        p.write_text(textwrap.dedent("""\
            pub fn identity<T>(value: T) -> T {
                value
            }
        """))
        result = extractor.extract_file_full(p)
        names = [e.name for e in result.entities]
        assert "identity" in names

    def test_empty_rust_file(self, extractor, tmp_path):
        p = tmp_path / "empty.rs"
        p.write_text("")
        result = extractor.extract_file_full(p)
        assert result.entities == []

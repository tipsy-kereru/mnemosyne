"""
Tests for SPEC-SESSION-002 T1-T3: scope_id/source_channel parameters
on extraction pipeline (code_parser, slm_extractor).

TDD RED phase: all tests written BEFORE implementation.
"""

from dataclasses import asdict

import pytest

from mnemosyne.extraction.deterministic.code_parser import CodeEntity, TreeSitterExtractor
from mnemosyne.extraction.semantic.slm_extractor import (
    ExtractedEntity,
    ExtractedRelation,
    GLiNER2Extractor,
    REBELExtractor,
    SemanticExtractor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_py_file(tmp_path):
    """Create a minimal Python source file for extraction."""
    src = tmp_path / "sample.py"
    src.write_text(
        "def greet(name: str) -> str:\n"
        "    return f'Hello {name}'\n"
        "\n"
        "class Greeter:\n"
        "    pass\n"
    )
    return src


@pytest.fixture
def sample_js_file(tmp_path):
    """Create a minimal JavaScript source file for extraction."""
    src = tmp_path / "sample.js"
    src.write_text(
        "function hello(name) {\n"
        "  return 'Hello ' + name;\n"
        "}\n"
        "\n"
        "class App extends React.Component {\n"
        "}\n"
    )
    return src


@pytest.fixture
def sample_go_file(tmp_path):
    """Create a minimal Go source file for extraction."""
    src = tmp_path / "sample.go"
    src.write_text(
        "package main\n"
        "\n"
        "func (s *Server) Handle() error {\n"
        "    return nil\n"
        "}\n"
        "\n"
        "type Config struct {\n"
        "}\n"
    )
    return src


@pytest.fixture
def sample_rust_file(tmp_path):
    """Create a minimal Rust source file for extraction."""
    src = tmp_path / "sample.rs"
    src.write_text(
        "pub fn process(input: &str) -> String {\n"
        "    input.to_string()\n"
        "}\n"
        "\n"
        "struct Item {\n"
        "    name: String,\n"
        "}\n"
        "\n"
        "enum Status {\n"
        "    Active,\n"
        "    Inactive,\n"
        "}\n"
    )
    return src


@pytest.fixture
def extractor():
    """TreeSitterExtractor instance."""
    return TreeSitterExtractor()


@pytest.fixture
def multi_lang_dir(tmp_path, sample_py_file, sample_js_file):
    """Directory with multiple source files for directory extraction."""
    return tmp_path


# ===================================================================
# T1: code_parser.py tests
# ===================================================================


class TestCodeEntityScopeFields:
    """CodeEntity dataclass accepts scope_id and source_channel."""

    def test_code_entity_scope_fields_default_none(self):
        """CodeEntity() has scope_id=None, source_channel=None by default."""
        entity = CodeEntity(
            type='function',
            name='foo',
            language='python',
            file_path='test.py',
            line_start=1,
            line_end=1,
            properties={},
        )
        assert entity.scope_id is None
        assert entity.source_channel is None

    def test_code_entity_scope_fields_set(self):
        """CodeEntity(scope_id='s1', source_channel='slack') works."""
        entity = CodeEntity(
            type='function',
            name='foo',
            language='python',
            file_path='test.py',
            line_start=1,
            line_end=1,
            properties={},
            scope_id='s1',
            source_channel='slack',
        )
        assert entity.scope_id == 's1'
        assert entity.source_channel == 'slack'


class TestExtractFileWithScope:
    """extract_file() accepts and propagates scope params."""

    def test_extract_file_with_scope(self, extractor, sample_py_file):
        """extract_file(path, scope_id='s1', source_channel='slack')
        returns entities with those values."""
        entities = extractor.extract_file(
            sample_py_file,
            scope_id='s1',
            source_channel='slack',
        )
        assert len(entities) > 0
        for e in entities:
            assert e.scope_id == 's1'
            assert e.source_channel == 'slack'

    def test_extract_file_without_scope(self, extractor, sample_py_file):
        """extract_file(path) returns entities with scope_id=None."""
        entities = extractor.extract_file(sample_py_file)
        assert len(entities) > 0
        for e in entities:
            assert e.scope_id is None
            assert e.source_channel is None

    def test_extract_file_python_scope(self, extractor, sample_py_file):
        """Python extraction propagates scope to all extracted entities."""
        entities = extractor.extract_file(
            sample_py_file, scope_id='proj-1', source_channel='code',
        )
        names = {e.name for e in entities}
        assert 'greet' in names
        assert 'Greeter' in names
        for e in entities:
            assert e.scope_id == 'proj-1'
            assert e.source_channel == 'code'

    def test_extract_file_js_scope(self, extractor, sample_js_file):
        """JS/TS extraction propagates scope."""
        entities = extractor.extract_file(
            sample_js_file, scope_id='js-proj', source_channel='discord',
        )
        assert len(entities) > 0
        for e in entities:
            assert e.scope_id == 'js-proj'
            assert e.source_channel == 'discord'

    def test_extract_file_go_scope(self, extractor, sample_go_file):
        """Go extraction propagates scope."""
        entities = extractor.extract_file(
            sample_go_file, scope_id='go-proj', source_channel='slack',
        )
        assert len(entities) > 0
        for e in entities:
            assert e.scope_id == 'go-proj'
            assert e.source_channel == 'slack'

    def test_extract_file_rust_scope(self, extractor, sample_rust_file):
        """Rust extraction propagates scope."""
        entities = extractor.extract_file(
            sample_rust_file, scope_id='rs-proj', source_channel='email',
        )
        assert len(entities) > 0
        for e in entities:
            assert e.scope_id == 'rs-proj'
            assert e.source_channel == 'email'


class TestExtractDirectoryScope:
    """extract_directory() propagates scope to all files."""

    def test_extract_directory_propagates_scope(self, extractor, multi_lang_dir):
        """extract_directory propagates scope_id and source_channel."""
        entities = extractor.extract_directory(
            multi_lang_dir,
            scope_id='dir-scope',
            source_channel='joplin',
        )
        assert len(entities) > 0
        for e in entities:
            assert e.scope_id == 'dir-scope'
            assert e.source_channel == 'joplin'

    def test_extract_directory_without_scope(self, extractor, multi_lang_dir):
        """extract_directory without scope returns entities with None fields."""
        entities = extractor.extract_directory(multi_lang_dir)
        assert len(entities) > 0
        for e in entities:
            assert e.scope_id is None
            assert e.source_channel is None


class TestToWikiFormatScope:
    """to_wiki_format() includes scope info when present."""

    def test_to_wiki_format_with_scope(self, extractor):
        """Wiki output includes scope info when scope_id is present."""
        entities = [
            CodeEntity(
                type='function',
                name='foo',
                language='python',
                file_path='test.py',
                line_start=1,
                line_end=1,
                properties={},
                scope_id='s1',
                source_channel='slack',
            ),
        ]
        output = extractor.to_wiki_format(entities)
        assert 's1' in output
        assert 'slack' in output

    def test_to_wiki_format_without_scope(self, extractor):
        """Wiki output is unchanged when no scope is set."""
        entities = [
            CodeEntity(
                type='function',
                name='bar',
                language='python',
                file_path='test.py',
                line_start=1,
                line_end=1,
                properties={},
            ),
        ]
        output = extractor.to_wiki_format(entities)
        assert 'bar' in output
        # Should not contain scope-specific labels when no scope
        assert 'scope_id' not in output
        assert 'source_channel' not in output


# ===================================================================
# T2: slm_extractor.py tests
# ===================================================================


class TestExtractedEntityScopeFields:
    """ExtractedEntity dataclass accepts scope fields."""

    def test_extracted_entity_scope_fields(self):
        """ExtractedEntity accepts scope_id and source_channel."""
        entity = ExtractedEntity(
            type='PERSON',
            text='John Smith',
            confidence=0.9,
            source='rule-based',
            start=0,
            end=10,
            scope_id='s1',
            source_channel='slack',
        )
        assert entity.scope_id == 's1'
        assert entity.source_channel == 'slack'

    def test_extracted_entity_scope_defaults(self):
        """ExtractedEntity defaults scope fields to None."""
        entity = ExtractedEntity(
            type='PERSON',
            text='Jane',
            confidence=0.8,
            source='rule-based',
            start=0,
            end=4,
        )
        assert entity.scope_id is None
        assert entity.source_channel is None


class TestExtractedRelationScopeFields:
    """ExtractedRelation dataclass accepts scope fields."""

    def test_extracted_relation_scope_fields(self):
        """ExtractedRelation accepts scope_id and source_channel."""
        rel = ExtractedRelation(
            subject='John',
            relation='works_for',
            object='Google',
            confidence=0.8,
            source='rule-based',
            scope_id='s2',
            source_channel='discord',
        )
        assert rel.scope_id == 's2'
        assert rel.source_channel == 'discord'

    def test_extracted_relation_scope_defaults(self):
        """ExtractedRelation defaults scope fields to None."""
        rel = ExtractedRelation(
            subject='A',
            relation='is_a',
            object='B',
            confidence=0.7,
            source='rule-based',
        )
        assert rel.scope_id is None
        assert rel.source_channel is None


class TestGLiNER2ScopePropagation:
    """GLiNER2Extractor propagates scope through fallback path."""

    @pytest.fixture
    def gliner(self):
        """GLiNER2Extractor (model likely unavailable, uses fallback)."""
        return GLiNER2Extractor()

    def test_gliner2_extract_with_scope_fallback(self, gliner):
        """GLiNER2 fallback path propagates scope to extracted entities."""
        text = "John Smith works at Google Inc."
        entities = gliner.extract(
            text,
            entity_types=['PERSON', 'ORGANIZATION'],
            scope_id='scope-abc',
            source_channel='email',
        )
        # Fallback should find at least PERSON via pattern
        for e in entities:
            assert e.scope_id == 'scope-abc'
            assert e.source_channel == 'email'

    def test_gliner2_extract_without_scope(self, gliner):
        """GLiNER2 without scope params returns None fields."""
        text = "Jane Doe lives in NYC."
        entities = gliner.extract(text, entity_types=['PERSON'])
        for e in entities:
            assert e.scope_id is None
            assert e.source_channel is None


class TestREBELScopePropagation:
    """REBELExtractor propagates scope through fallback path."""

    @pytest.fixture
    def rebel(self):
        """REBELExtractor (model likely unavailable, uses fallback)."""
        return REBELExtractor()

    def test_rebel_extract_with_scope_fallback(self, rebel):
        """REBEL fallback path propagates scope to extracted relations."""
        text = "Alice works for Google"
        relations = rebel.extract(
            text,
            scope_id='rel-scope',
            source_channel='slack',
        )
        for r in relations:
            assert r.scope_id == 'rel-scope'
            assert r.source_channel == 'slack'

    def test_rebel_extract_without_scope(self, rebel):
        """REBEL without scope params returns None fields."""
        text = "Bob is located in Seattle"
        relations = rebel.extract(text)
        for r in relations:
            assert r.scope_id is None
            assert r.source_channel is None


class TestSemanticExtractorScope:
    """SemanticExtractor propagates scope to both NER and RE."""

    @pytest.fixture
    def semantic(self):
        """SemanticExtractor (models likely unavailable, uses fallbacks)."""
        return SemanticExtractor()

    def test_semantic_extract_with_scope(self, semantic):
        """SemanticExtractor propagates scope to NER and RE results."""
        text = "John Smith works for Google Inc. and lives in San Francisco."
        result = semantic.extract(
            text,
            entity_types=['PERSON', 'ORGANIZATION'],
            scope_id='sem-scope',
            source_channel='joplin',
        )
        # Check entities carry scope
        for e_dict in result['entities']:
            assert e_dict.get('scope_id') == 'sem-scope'
            assert e_dict.get('source_channel') == 'joplin'
        # Check relations carry scope
        for r_dict in result['relations']:
            assert r_dict.get('scope_id') == 'sem-scope'
            assert r_dict.get('source_channel') == 'joplin'

    def test_semantic_extract_without_scope(self, semantic):
        """Backward compat: no scope params = None fields."""
        text = "Jane lives in NYC."
        result = semantic.extract(text, entity_types=['PERSON'])
        for e_dict in result['entities']:
            assert e_dict.get('scope_id') is None
            assert e_dict.get('source_channel') is None
        for r_dict in result['relations']:
            assert r_dict.get('scope_id') is None
            assert r_dict.get('source_channel') is None


class TestAsdictIncludesScope:
    """asdict() serialization includes scope fields for forward compat."""

    def test_asdict_includes_scope_entity(self):
        """asdict(ExtractedEntity) includes scope_id and source_channel."""
        entity = ExtractedEntity(
            type='PERSON',
            text='Alice',
            confidence=0.9,
            source='rule-based',
            start=0,
            end=5,
            scope_id='s3',
            source_channel='code',
        )
        d = asdict(entity)
        assert 'scope_id' in d
        assert 'source_channel' in d
        assert d['scope_id'] == 's3'
        assert d['source_channel'] == 'code'

    def test_asdict_includes_scope_relation(self):
        """asdict(ExtractedRelation) includes scope_id and source_channel."""
        rel = ExtractedRelation(
            subject='A',
            relation='is_a',
            object='B',
            confidence=0.8,
            source='rule-based',
            scope_id='s4',
            source_channel='discord',
        )
        d = asdict(rel)
        assert 'scope_id' in d
        assert 'source_channel' in d
        assert d['scope_id'] == 's4'
        assert d['source_channel'] == 'discord'

    def test_asdict_includes_scope_code_entity(self):
        """asdict(CodeEntity) includes scope_id and source_channel."""
        entity = CodeEntity(
            type='function',
            name='foo',
            language='python',
            file_path='test.py',
            line_start=1,
            line_end=1,
            properties={},
            scope_id='s5',
            source_channel='slack',
        )
        d = asdict(entity)
        assert 'scope_id' in d
        assert 'source_channel' in d
        assert d['scope_id'] == 's5'
        assert d['source_channel'] == 'slack'

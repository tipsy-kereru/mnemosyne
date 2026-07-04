"""
Tests for auto-link system.
"""

import pytest

from mnemosyne.link.extractor import LinkExtractor
from mnemosyne.link.auto_linker import AutoLinker


class TestLinkExtractor:
    """Tests for LinkExtractor."""

    def test_extract_markdown_links(self):
        """Should extract standard markdown links."""
        extractor = LinkExtractor()

        markdown = "See [Tesla](organizations/tesla) for more info."
        links = extractor.extract_links(markdown)

        assert len(links) == 1
        assert links[0] == ("Tesla", "organizations/tesla", pytest.approx("See [Tesla](organizations/tesla) for more info."))

    def test_extract_wiki_links(self):
        """Should extract wiki-style links."""
        extractor = LinkExtractor()

        markdown = "See [[organizations/tesla]] for more."
        links = extractor.extract_links(markdown)

        assert len(links) == 1
        assert links[0][0] == "organizations/tesla"
        assert links[0][1] == "organizations/tesla"

    def test_extract_wiki_links_with_label(self):
        """Should extract wiki links with labels."""
        extractor = LinkExtractor()

        markdown = "See [[organizations/tesla|Tesla]] for more."
        links = extractor.extract_links(markdown)

        assert len(links) == 1
        assert links[0][0] == "Tesla"
        assert links[0][1] == "organizations/tesla"

    def test_extract_multiple_links(self):
        """Should extract multiple links."""
        extractor = LinkExtractor()

        markdown = "[Tesla](orgs/tesla) and [SpaceX](orgs/spacex)"
        links = extractor.extract_links(markdown)

        assert len(links) == 2

    def test_extract_no_links(self):
        """Should handle text with no links."""
        extractor = LinkExtractor()

        markdown = "Just plain text with no links."
        links = extractor.extract_links(markdown)

        assert len(links) == 0

    def test_infer_link_type_works_at(self):
        """Should infer 'works_at' from context."""
        extractor = LinkExtractor()

        context = "John works at Tesla"
        link_type = extractor.infer_link_type("person", "tesla", context)

        assert link_type == "works_at"

    def test_infer_link_type_attended(self):
        """Should infer 'attended' from context."""
        extractor = LinkExtractor()

        context = "She attended the summit"
        link_type = extractor.infer_link_type("person", "summit", context)

        assert link_type == "attended"

    def test_infer_link_type_fallback(self):
        """Should fallback to 'mentions' for unknown contexts."""
        extractor = LinkExtractor()

        context = "See Tesla for details"
        link_type = extractor.infer_link_type("person", "tesla", context)

        assert link_type == "mentions"

    def test_infer_link_type_no_context(self):
        """Should return None when no context."""
        extractor = LinkExtractor()

        link_type = extractor.infer_link_type("person", "tesla", None)

        assert link_type is None

    def test_extract_and_infer(self):
        """Should extract and infer in one pass."""
        extractor = LinkExtractor()

        markdown = "John works at [Tesla](organizations/tesla)."
        links = extractor.extract_and_infer(markdown, "person")

        assert len(links) == 1
        assert links[0][2] == "works_at"

    def test_count_links(self):
        """Should count links correctly."""
        extractor = LinkExtractor()

        markdown = "[A](path1) and [B](path2)"
        count = extractor.count_links(markdown)

        assert count == 2

    def test_has_links_true(self):
        """Should detect presence of links."""
        extractor = LinkExtractor()

        markdown = "[Link](path)"
        assert extractor.has_links(markdown) is True

    def test_has_links_false(self):
        """Should detect absence of links."""
        extractor = LinkExtractor()

        markdown = "No links here"
        assert extractor.has_links(markdown) is False


class TestAutoLinker:
    """Tests for AutoLinker."""

    def test_initialization(self):
        """AutoLinker should initialize with kg and schema."""
        # Mock knowledge graph
        class MockKG:
            def get_entity(self, entity_id):
                return None

            def query(self, query, limit=5):
                return []

            def add_entity(self, entity_id, entity_type, name, properties):
                pass

            def add_relation(self, relation_id, from_entity, to_entity, relation_type, properties):
                pass

        class MockSchema:
            def infer_type(self, path):
                return None

        kg = MockKG()
        schema = MockSchema()
        auto_linker = AutoLinker(kg, schema)

        assert auto_linker.kg is kg
        assert auto_linker.schema is schema

    def test_on_entity_write_no_links(self):
        """Should handle content with no links."""
        class MockKG:
            pass

        auto_linker = AutoLinker(MockKG())
        count = auto_linker.on_entity_write("e1", "No links here")

        assert count == 0

    def test_on_entity_write_empty_content(self):
        """Should handle empty content."""
        class MockKG:
            pass

        auto_linker = AutoLinker(MockKG())
        count = auto_linker.on_entity_write("e1", "")

        assert count == 0

    def test_resolve_target_by_id(self):
        """Should resolve target by direct ID."""
        class MockEntity:
            def __init__(self, id):
                self.id = id

        class MockKG:
            def get_entity(self, entity_id):
                return MockEntity(entity_id)

        auto_linker = AutoLinker(MockKG())
        result = auto_linker._resolve_target("test-entity")

        assert result == "test-entity"

    def test_resolve_target_not_found(self):
        """Should return None for unknown target."""
        class MockKG:
            def get_entity(self, entity_id):
                return None

            def query(self, query, limit=5):
                return []

        auto_linker = AutoLinker(MockKG())
        result = auto_linker._resolve_target("unknown")

        assert result is None

    def test_create_stub_entity_id_generation(self):
        """Should generate entity ID from path."""
        created_id = None

        class MockKG:
            def add_entity(self, entity_id, entity_type, name, properties):
                nonlocal created_id
                created_id = entity_id

        auto_linker = AutoLinker(MockKG())
        auto_linker._create_stub("organizations/tesla motors")

        assert created_id == "organizations_tesla-motors"

    def test_create_stub_with_schema_type_inference(self):
        """Should use schema for type inference."""
        created_type = None

        class MockKG:
            def add_entity(self, entity_id, entity_type, name, properties):
                nonlocal created_type
                created_type = entity_type

        class MockSchema:
            def infer_type(self, path):
                return "organization"

        auto_linker = AutoLinker(MockKG(), MockSchema())
        auto_linker._create_stub("organizations/tesla")

        assert created_type == "organization"

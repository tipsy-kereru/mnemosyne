"""
Tests for SPEC-HEADROOM-001 broken-link / stale-entity detection (REQ-008).

Covers:
- AC6: a broken ``[[entity:function:deleted_func]]`` link is detected and reported.
"""


import pytest

from mnemosyne.graph.knowledge_graph import KnowledgeGraph, Entity
from mnemosyne.graph.maintenance import BrokenLink, find_broken_links


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_broken.db")


@pytest.fixture
def kg(db_path):
    graph = KnowledgeGraph(db_path=db_path)
    yield graph
    graph.close()


class TestBrokenEntityLinks:
    def test_broken_entity_link_detected(self, kg):
        """AC6: [[entity:function:deleted_func]] is reported when target absent."""
        kg.add_entity(
            Entity(
                id="doc1",
                type="note",
                name="design doc",
                properties={"body": "See [[entity:function:deleted_func]] for details."},
                created_at="",
                updated_at="",
            )
        )
        result = find_broken_links(kg)
        assert isinstance(result, list)
        targets = {b.target for b in result}
        assert "entity:function:deleted_func" in targets

    def test_valid_entity_link_not_flagged(self, kg):
        kg.add_entity(
            Entity(
                id="fn_exists",
                type="function",
                name="real_func",
                properties={},
                created_at="",
                updated_at="",
            )
        )
        kg.add_entity(
            Entity(
                id="doc2",
                type="note",
                name="doc",
                properties={"body": "Calls [[entity:function:real_func]]."},
                created_at="",
                updated_at="",
            )
        )
        result = find_broken_links(kg)
        targets = {b.target for b in result}
        assert "entity:function:real_func" not in targets

    def test_broken_link_records_source_entity(self, kg):
        """The report records which entity held the broken link."""
        kg.add_entity(
            Entity(
                id="holder",
                type="note",
                name="holder",
                properties={"body": "[[entity:function:ghost]]"},
                created_at="",
                updated_at="",
            )
        )
        result = find_broken_links(kg)
        assert len(result) == 1
        link = result[0]
        assert isinstance(link, BrokenLink)
        assert link.source == "holder"
        assert link.target == "entity:function:ghost"
        assert link.kind == "entity"

    def test_multiple_broken_links(self, kg):
        kg.add_entity(
            Entity(
                id="multi",
                type="note",
                name="multi",
                properties={
                    "body": "[[entity:function:ghost1]] and [[entity:task:ghost2]]"
                },
                created_at="",
                updated_at="",
            )
        )
        result = find_broken_links(kg)
        targets = {b.target for b in result}
        assert "entity:function:ghost1" in targets
        assert "entity:task:ghost2" in targets


class TestBrokenSourceFileLinks:
    def test_missing_source_file_flagged(self, kg):
        """Entity with a source_file pointing at a non-existent path is flagged."""
        kg.add_entity(
            Entity(
                id="sf1",
                type="function",
                name="fn",
                properties={"source_file": "/nonexistent/path/to/file.py"},
                created_at="",
                updated_at="",
            )
        )
        result = find_broken_links(kg)
        files = {b.target for b in result if b.kind == "source_file"}
        assert "/nonexistent/path/to/file.py" in files

    def test_existing_source_file_not_flagged(self, kg, tmp_path):
        real_file = tmp_path / "real.py"
        real_file.write_text("x = 1")
        kg.add_entity(
            Entity(
                id="sf2",
                type="function",
                name="fn",
                properties={"source_file": str(real_file)},
                created_at="",
                updated_at="",
            )
        )
        result = find_broken_links(kg)
        files = {b.target for b in result if b.kind == "source_file"}
        assert str(real_file) not in files


class TestNoMutation:
    def test_detector_never_mutates(self, kg):
        """REQ-008: the detector surfaces only, never deletes/renames."""
        kg.add_entity(
            Entity(
                id="keepme",
                type="note",
                name="keepme",
                properties={"body": "[[entity:function:ghost]]"},
                created_at="",
                updated_at="",
            )
        )
        before = kg.get_entity("keepme")
        find_broken_links(kg)
        after = kg.get_entity("keepme")
        assert before.properties == after.properties
        assert before.name == after.name
        # No entity was deleted
        assert kg.get_entity("keepme") is not None


class TestWikiLinkScanning:
    def test_scans_wiki_markdown_files(self, kg, tmp_path):
        """The detector also scans .md files under a wiki root for [[...]] links."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "doc.md").write_text(
            "# Doc\nReferences [[entity:function:wikighost]].\n"
        )
        result = find_broken_links(kg, wiki_root=wiki)
        targets = {b.target for b in result}
        assert "entity:function:wikighost" in targets

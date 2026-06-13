"""
Tests for SPEC-HEADROOM-001 content_hash change detection (REQ-006, REQ-007)
and the skip-unchanged fast path on update_entity.

Covers AC4 (content_hash column added NULL, existing rows unaffected) and
AC5 (re-extraction of byte-identical source content skips the rewrite).
"""

import sqlite3

import pytest

from mnemosyne.graph.knowledge_graph import KnowledgeGraph, Entity
from mnemosyne.graph.hash_sync import compute_content_hash, should_skip


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_hash.db")


@pytest.fixture
def kg(db_path):
    graph = KnowledgeGraph(db_path=db_path)
    yield graph
    graph.close()


# -- compute_content_hash / should_skip helpers --


class TestHashHelpers:
    def test_compute_hash_is_deterministic(self):
        assert compute_content_hash("hello world") == compute_content_hash("hello world")

    def test_compute_hash_differs_on_content(self):
        assert compute_content_hash("a") != compute_content_hash("b")

    def test_compute_hash_returns_hex_sha256(self):
        h = compute_content_hash("x")
        # sha256 hex digest is 64 chars
        assert len(h) == 64
        int(h, 16)  # parses as hex

    def test_compute_hash_is_canonical_utf8(self):
        # Match hashlib.sha256(content.encode('utf-8'))
        import hashlib

        assert compute_content_hash("café") == hashlib.sha256("café".encode("utf-8")).hexdigest()

    def test_should_skip_true_when_hashes_equal(self):
        assert should_skip(stored_hash="abc", new_hash="abc") is True

    def test_should_skip_false_when_hashes_differ(self):
        assert should_skip(stored_hash="abc", new_hash="def") is False

    def test_should_skip_false_when_stored_is_none(self):
        # No prior hash -> never skip (must persist the first hash)
        assert should_skip(stored_hash=None, new_hash="abc") is False


# -- AC4: content_hash column additive, NULL for existing rows --


class TestContentHashSchema:
    def test_content_hash_column_exists(self, kg):
        cols = kg._get_table_columns("entities")
        assert "content_hash" in cols

    def test_content_hash_defaults_null_for_new_entity(self, kg):
        e = Entity(
            id="ch1", type="task", name="T", properties={},
            created_at="", updated_at="",
        )
        kg.add_entity(e)
        row = kg.conn.execute(
            "SELECT content_hash FROM entities WHERE id = ?", ("ch1",)
        ).fetchone()
        assert row["content_hash"] is None

    def test_content_hash_null_for_preexisting_rows(self, tmp_path):
        """AC4: existing rows keep prior values; new column is NULL."""
        db_path = str(tmp_path / "preexist_hash.db")
        # Build a DB with the OLD schema (no content_hash column)
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE entities (
                id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
                properties TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                version INTEGER DEFAULT 1
            )"""
        )
        conn.execute(
            """INSERT INTO entities VALUES
                ('old', 'task', 'Old Task', '{}', '2020-01-01', '2020-01-01', 1)"""
        )
        conn.commit()
        conn.close()

        kg = KnowledgeGraph(db_path=db_path)
        row = kg.conn.execute(
            "SELECT content_hash FROM entities WHERE id = ?", ("old",)
        ).fetchone()
        assert row["content_hash"] is None
        # Prior data preserved
        entity = kg.get_entity("old")
        assert entity.name == "Old Task"
        kg.close()


# -- AC5: skip-unchanged fast path on re-extraction --


class TestSkipUnchangedFastPath:
    def _add(self, kg, eid="skip1"):
        e = Entity(
            id=eid, type="function", name="do_thing", properties={"sig": "()"},
            created_at="", updated_at="",
        )
        kg.add_entity(e)
        return e

    def test_skip_when_content_identical(self, kg):
        self._add(kg)
        existing = kg.get_entity("skip1")
        original_version = existing.version

        # First update persists the hash
        e1 = kg.get_entity("skip1")
        e1.properties = {"sig": "()"}
        kg.update_entity(e1, skip_if_unchanged=True, source_content="def do_thing(): pass")
        after_first = kg.get_entity("skip1")
        assert after_first.version == original_version + 1
        stored_hash = kg.conn.execute(
            "SELECT content_hash FROM entities WHERE id = 'skip1'"
        ).fetchone()["content_hash"]
        assert stored_hash is not None

        # Second call with identical source_content -> MUST skip
        e2 = kg.get_entity("skip1")
        e2.properties = {"sig": "()"}
        result = kg.update_entity(
            e2, skip_if_unchanged=True, source_content="def do_thing(): pass"
        )
        after_skip = kg.get_entity("skip1")
        assert after_skip.version == after_first.version  # unchanged
        assert after_skip.updated_at == after_first.updated_at  # unchanged
        assert result is not None

    def test_skip_emits_no_history_row(self, kg):
        self._add(kg, "skip2")
        # Persist hash
        e = kg.get_entity("skip2")
        kg.update_entity(e, skip_if_unchanged=True, source_content="v1")
        history_count = kg.conn.execute(
            "SELECT COUNT(*) FROM entity_history WHERE entity_id = 'skip2'"
        ).fetchone()[0]

        # Re-extract identical content
        e2 = kg.get_entity("skip2")
        kg.update_entity(e2, skip_if_unchanged=True, source_content="v1")
        after = kg.conn.execute(
            "SELECT COUNT(*) FROM entity_history WHERE entity_id = 'skip2'"
        ).fetchone()[0]
        assert after == history_count  # no new history row

    def test_no_skip_when_content_changed(self, kg):
        self._add(kg, "skip3")
        e = kg.get_entity("skip3")
        kg.update_entity(e, skip_if_unchanged=True, source_content="v1")
        before = kg.get_entity("skip3")

        e2 = kg.get_entity("skip3")
        kg.update_entity(e2, skip_if_unchanged=True, source_content="v2-changed")
        after = kg.get_entity("skip3")
        assert after.version == before.version + 1
        new_hash = kg.conn.execute(
            "SELECT content_hash FROM entities WHERE id = 'skip3'"
        ).fetchone()["content_hash"]
        assert new_hash == compute_content_hash("v2-changed")

    def test_skip_disabled_by_default_preserves_existing_callers(self, kg):
        """REQ-007: fast path is opt-in. Default still writes on every call."""
        self._add(kg, "skip4")
        e = kg.get_entity("skip4")
        kg.update_entity(e, source_content="identical")  # no skip flag
        v1 = kg.get_entity("skip4")

        e2 = kg.get_entity("skip4")
        kg.update_entity(e2, source_content="identical")  # still no skip flag
        v2 = kg.get_entity("skip4")
        assert v2.version == v1.version + 1  # wrote unconditionally

    def test_skip_with_no_source_content_never_skips(self, kg):
        """If source_content is not provided, the fast path cannot decide -> never skip."""
        self._add(kg, "skip5")
        e = kg.get_entity("skip5")
        # skip_if_unchanged=True but no source_content -> must NOT skip
        kg.update_entity(e, skip_if_unchanged=True)
        after = kg.get_entity("skip5")
        assert after.version == 2  # wrote normally

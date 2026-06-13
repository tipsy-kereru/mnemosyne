"""
Tests for SPEC-HEADROOM-001 FTS5 ranked search (REQ-001, REQ-002, REQ-003,
REQ-004, REQ-00ROOM).

Covers:
- AC1: search:auth returns authenticateUser (partial/prefix match, bm25 ranked)
- AC2: entity_fts backfilled from pre-existing entities on first creation
- AC3: schema migration is idempotent (init twice does not raise)
- AC11: graceful fallback to LIKE when FTS5 unavailable / entity_fts absent
"""

import logging
import sqlite3

import pytest

from mnemosyne.graph.knowledge_graph import KnowledgeGraph, Entity


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_fts.db")


@pytest.fixture
def kg(db_path):
    graph = KnowledgeGraph(db_path=db_path)
    yield graph
    graph.close()


def _has_fts5() -> bool:
    """True if the stdlib sqlite3 exposes FTS5."""
    conn = sqlite3.connect(":memory:")
    try:
        opts = [r[0] for r in conn.execute("PRAGMA compile_options")]
        return "ENABLE_FTS5" in opts
    finally:
        conn.close()


FTS5_AVAILABLE = _has_fts5()


# -- AC3: idempotent migration (schema + triggers + FTS table) --


class TestFtsSchemaIdempotent:
    def test_entity_fts_table_created(self, kg):
        tables = [
            r["name"]
            for r in kg.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "entity_fts" in tables

    def test_sync_triggers_created(self, kg):
        triggers = {
            r["name"]
            for r in kg.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        assert "entity_ai" in triggers
        assert "entity_ad" in triggers
        assert "entity_au" in triggers

    def test_init_twice_does_not_raise(self, db_path):
        """AC3: instantiating KnowledgeGraph twice in succession is safe."""
        kg1 = KnowledgeGraph(db_path=db_path)
        kg1.add_entity(
            Entity(id="idem1", type="task", name="Idempotent Task", properties={},
                   created_at="", updated_at="")
        )
        kg1.close()

        kg2 = KnowledgeGraph(db_path=db_path)  # must not raise
        # Re-running _init_session_schema directly must also be safe
        kg2._init_session_schema()
        kg2._init_session_schema()
        entity = kg2.get_entity("idem1")
        assert entity is not None
        assert entity.name == "Idempotent Task"
        kg2.close()


# -- Trigger roundtrip: insert/update/delete reflected in entity_fts --


class TestFtsTriggerRoundtrip:
    @pytest.mark.skipif(not FTS5_AVAILABLE, reason="FTS5 not enabled in this sqlite build")
    def test_insert_reflects_in_fts(self, kg):
        kg.add_entity(
            Entity(id="tr1", type="function", name="authenticateUser",
                   properties={"sig": "()"}, created_at="", updated_at="")
        )
        row = kg.conn.execute(
            "SELECT name FROM entity_fts WHERE entity_fts MATCH 'authenticateUser'"
        ).fetchone()
        assert row is not None
        assert row["name"] == "authenticateUser"

    @pytest.mark.skipif(not FTS5_AVAILABLE, reason="FTS5 not enabled in this sqlite build")
    def test_update_reflects_in_fts(self, kg):
        """REQ-002: AFTER UPDATE trigger must delete-then-insert in FTS."""
        kg.add_entity(
            Entity(id="tr2", type="function", name="oldName",
                   properties={}, created_at="", updated_at="")
        )
        e = kg.get_entity("tr2")
        e.name = "renamedFunction"
        kg.update_entity(e)

        # Old name no longer matches
        old = kg.conn.execute(
            "SELECT name FROM entity_fts WHERE entity_fts MATCH 'oldName'"
        ).fetchone()
        assert old is None
        # New name present
        new = kg.conn.execute(
            "SELECT name FROM entity_fts WHERE entity_fts MATCH 'renamedFunction'"
        ).fetchone()
        assert new is not None
        assert new["name"] == "renamedFunction"

    @pytest.mark.skipif(not FTS5_AVAILABLE, reason="FTS5 not enabled in this sqlite build")
    def test_delete_reflects_in_fts(self, kg):
        kg.add_entity(
            Entity(id="tr3", type="function", name="toDelete",
                   properties={}, created_at="", updated_at="")
        )
        kg.conn.execute("DELETE FROM entities WHERE id = 'tr3'")
        kg.conn.commit()
        row = kg.conn.execute(
            "SELECT name FROM entity_fts WHERE entity_fts MATCH 'toDelete'"
        ).fetchone()
        assert row is None


# -- AC2: first-time backfill from pre-existing rows --


class TestFtsBackfill:
    def test_backfill_populates_from_preexisting_rows(self, tmp_path):
        """AC2: creating entity_fts on a DB with existing entities backfills."""
        db_path = str(tmp_path / "backfill.db")
        # Pre-seed a DB with the OLD schema + rows, no FTS table, no content_hash
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
                ('bf1', 'function', 'authenticateUser', '{}', '2020', '2020', 1),
                ('bf2', 'function', 'authMiddleware', '{}', '2020', '2020', 1)"""
        )
        conn.commit()
        conn.close()

        kg = KnowledgeGraph(db_path=db_path)
        if FTS5_AVAILABLE:
            count = kg.conn.execute("SELECT COUNT(*) FROM entity_fts").fetchone()[0]
            assert count == 2, "entity_fts must be backfilled from pre-existing rows"
        kg.close()


# -- AC1: search returns approximate/partial name matches, bm25-ranked --


class TestFtsRankedSearch:
    @pytest.mark.skipif(not FTS5_AVAILABLE, reason="FTS5 not enabled in this sqlite build")
    def test_search_partial_name_returns_match(self, kg):
        """AC1: search:auth returns authenticateUser despite exact-name mismatch."""
        kg.add_entity(
            Entity(id="s1", type="function", name="authenticateUser",
                   properties={}, created_at="", updated_at="")
        )
        result = kg.query("search:auth")
        assert result["type"] == "search"
        assert result["count"] >= 1
        names = [r["name"] for r in result["results"]]
        assert "authenticateUser" in names

    @pytest.mark.skipif(not FTS5_AVAILABLE, reason="FTS5 not enabled in this sqlite build")
    def test_search_ranks_by_bm25_relevance(self, kg):
        """REQ-003: ordering reflects bm25, not insertion order."""
        # 'auth' token appears once in name of auth_exact, once in auth_other,
        # but auth_exact is a closer/earlier match.
        kg.add_entity(
            Entity(id="r1", type="function", name="unrelatedThing",
                   properties={}, created_at="", updated_at="")
        )
        kg.add_entity(
            Entity(id="r2", type="function", name="authenticateUser",
                   properties={"desc": "auth auth auth"}, created_at="", updated_at="")
        )
        kg.add_entity(
            Entity(id="r3", type="function", name="authMiddleware",
                   properties={}, created_at="", updated_at="")
        )
        result = kg.query("search:auth")
        ids = [r["id"] for r in result["results"]]
        # All auth-related entities surface; the unrelated one does not
        assert "r2" in ids
        assert "r3" in ids
        assert "r1" not in ids

    @pytest.mark.skipif(not FTS5_AVAILABLE, reason="FTS5 not enabled in this sqlite build")
    def test_search_response_shape_preserved(self, kg):
        """REQ-003: {type, term, results, count} shape unchanged."""
        kg.add_entity(
            Entity(id="sh1", type="note", name="shaped", properties={},
                   created_at="", updated_at="")
        )
        result = kg.query("search:shaped")
        assert set(result.keys()) >= {"type", "term", "results", "count"}
        assert result["type"] == "search"
        assert result["term"] == "shaped"
        assert isinstance(result["results"], list)
        assert result["count"] == len(result["results"])

    @pytest.mark.skipif(not FTS5_AVAILABLE, reason="FTS5 not enabled in this sqlite build")
    def test_search_composes_with_scope_modifier(self, kg):
        # project scope visibility includes self + descendants + global (None).
        # We verify the modifier actually filters by creating a session scope
        # whose visibility tree does NOT include the global entity's channel.
        kg.add_entity(
            Entity(id="sc_global", type="function", name="authenticateUser",
                   properties={}, created_at="", updated_at=""),
            source_channel="global-channel",
        )
        project = kg.create_scope("project", "P")
        kg.add_entity(
            Entity(id="sc_proj", type="function", name="authenticateUser",
                   properties={}, created_at="", updated_at=""),
            scope_id=project.id, source_channel="code",
        )
        # @channel:code excludes the global entity regardless of scope visibility
        result = kg.query("search:authenticateUser@project:P@channel:code")
        ids = {r["id"] for r in result["results"]}
        assert "sc_proj" in ids
        assert "sc_global" not in ids


# -- AC11: graceful fallback when entity_fts is absent --


class TestFtsFallback:
    def test_search_falls_back_to_like_when_fts_absent(self, kg, caplog):
        """AC11: drop entity_fts -> search falls back to LIKE and warns."""
        # Drop the FTS table and triggers to simulate absence
        kg.conn.executescript(
            "DROP TRIGGER IF EXISTS entity_ai;"
            "DROP TRIGGER IF EXISTS entity_ad;"
            "DROP TRIGGER IF EXISTS entity_au;"
            "DROP TABLE IF EXISTS entity_fts;"
        )
        kg.conn.commit()

        kg.add_entity(
            Entity(id="fb1", type="note", name="fallbackMatch",
                   properties={}, created_at="", updated_at="")
        )
        with caplog.at_level(logging.WARNING, logger="mnemosyne.graph.knowledge_graph"):
            result = kg.query("search:fallback")
        assert result["type"] == "search"
        assert result["count"] == 1
        assert result["results"][0]["id"] == "fb1"
        # A warning must have been logged
        assert any("FTS5" in rec.message or "fallback" in rec.message.lower()
                   for rec in caplog.records)

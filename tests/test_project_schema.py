"""
Tests for the project domain schema pack and entity tombstone/timeline support.

Covers Phase 3 of the Onyx <-> Mnemosyne integration plan:
  * the project-v1 schema pack loads, inherits base types, and defines the new
    project-domain entity + link types
  * the new KnowledgeGraph tombstone/timeline methods behave per spec
  * new entity types round-trip through the knowledge graph
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph
from mnemosyne.schema.engine import SchemaEngine

# Locate the on-disk packs shipped with the package, regardless of cwd.
import mnemosyne.schema.engine as _engine_mod

_PACKS_SRC = Path(_engine_mod.__file__).resolve().parent / "packs"

# New entity types defined by the project-v1 pack.
PROJECT_ENTITY_TYPES = [
    "requirement",
    "client",
    "stakeholder",
    "action-item",
    "risk",
    "blocker",
    "release",
]

# New link types defined by the project-v1 pack: name -> (from, to, inferred).
PROJECT_LINK_TYPES = {
    "REQUESTED_BY": ("requirement", "stakeholder", False),
    "DECIDED_IN": ("decision", "meeting", False),
    "SUPERSEDES": ("entity", "entity", False),
    "CONFLICTS_WITH": ("entity", "entity", False),
    "IMPLEMENTS": ("entity", "requirement", False),
    "BLOCKS": ("blocker", "entity", False),
    "VERIFIED_BY": ("requirement", "release", False),
    "DERIVED_FROM": ("entity", "entity", True),
}

# Base-pack entity types that must be inherited (NOT redefined).
BASE_ENTITY_TYPES = ["entity", "person", "organization", "project",
                     "event", "meeting", "decision", "note", "reference"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_engine(tmp_path):
    """SchemaEngine pointed at a temp packs dir containing the real packs.

    Copies the shipped base-v1 and project-v1 packs verbatim so that
    inheritance resolves against the actual files on disk.
    """
    packs_dir = tmp_path / "schema-packs"
    builtin = packs_dir / "builtin"
    builtin.mkdir(parents=True)
    shutil.copytree(_PACKS_SRC / "base-v1", builtin / "base-v1")
    shutil.copytree(_PACKS_SRC / "project-v1", builtin / "project-v1")
    return SchemaEngine(packs_dir)


@pytest.fixture
def kg(tmp_path):
    """A fresh KnowledgeGraph backed by a temp database."""
    graph = KnowledgeGraph(str(tmp_path / "kg.db"))
    yield graph
    graph.close()


def _make_entity(eid: str, etype: str, name: str,
                 properties: Dict[str, Any]) -> Entity:
    """Build a minimal Entity for insertion."""
    return Entity(
        id=eid,
        type=etype,
        name=name,
        properties=properties,
        created_at="",
        updated_at="",
    )


# ---------------------------------------------------------------------------
# Schema pack tests
# ---------------------------------------------------------------------------

class TestProjectSchemaPack:
    """The project-v1 pack must load and expose all new types + inherited ones."""

    def test_pack_loads(self, project_engine):
        pack = project_engine.load_pack("project-v1")

        assert pack is not None
        assert pack.name == "project"
        assert pack.version == "1.0"
        assert pack.api_version == "1.0"

    def test_inherits_base(self, project_engine):
        pack = project_engine.load_pack("project-v1")

        assert pack is not None
        # The project pack declares inheritance from the base pack.
        assert pack.inherits == "base-v1"
        # All base types must be inherited, not redefined by project-v1.
        for base_type in BASE_ENTITY_TYPES:
            assert base_type in pack.types, f"missing inherited base type: {base_type}"

    def test_new_entity_types_present(self, project_engine):
        pack = project_engine.load_pack("project-v1")

        assert pack is not None
        for type_name in PROJECT_ENTITY_TYPES:
            assert type_name in pack.types, f"missing project type: {type_name}"

    def test_requirement_properties(self, project_engine):
        pack = project_engine.load_pack("project-v1")

        req = pack.types["requirement"]
        expected = {"title", "description", "status", "priority",
                    "requested_by", "accepted_at"}
        assert expected.issubset(set(req.properties.keys()))

    def test_risk_properties(self, project_engine):
        pack = project_engine.load_pack("project-v1")

        risk = pack.types["risk"]
        expected = {"title", "description", "severity", "likelihood",
                    "mitigation", "status"}
        assert expected.issubset(set(risk.properties.keys()))

    def test_new_link_types_present(self, project_engine):
        pack = project_engine.load_pack("project-v1")

        assert pack is not None
        for link_name, (from_type, to_type, inferred) in PROJECT_LINK_TYPES.items():
            assert link_name in pack.link_types, f"missing project link: {link_name}"
            link = pack.link_types[link_name]
            assert link.from_type == from_type
            assert link.to_type == to_type
            assert link.inferred is inferred

    def test_pack_format_matches_base(self):
        """The project pack must use the same top-level YAML shape as base-v1."""
        with open(_PACKS_SRC / "base-v1" / "pack.yaml") as f:
            base = yaml.safe_load(f)
        with open(_PACKS_SRC / "project-v1" / "pack.yaml") as f:
            project = yaml.safe_load(f)

        # Same top-level keys (project adds `inherits`).
        for key in ("api_version", "name", "version", "types",
                    "link_types", "search_defaults"):
            assert key in project, f"project pack missing key: {key}"

        # Each entity type uses the same field shape as base types.
        base_type_keys = set(next(iter(base["types"].values())).keys())
        for type_name, type_def in project["types"].items():
            for required_field in base_type_keys:
                assert required_field in type_def, (
                    f"type '{type_name}' missing field '{required_field}'"
                )

        # Each link type uses the same field shape as base links.
        base_link_keys = set(next(iter(base["link_types"].values())).keys())
        for link_name, link_def in project["link_types"].items():
            for required_field in base_link_keys:
                assert required_field in link_def, (
                    f"link '{link_name}' missing field '{required_field}'"
                )

        # api_version + search_defaults structure must match base.
        assert project["api_version"] == base["api_version"]
        assert set(project["search_defaults"].keys()) == set(base["search_defaults"].keys())


# ---------------------------------------------------------------------------
# Tombstone / timeline tests
# ---------------------------------------------------------------------------

class TestTombstone:
    def test_tombstone_sets_valid_to_and_increments_version(self, kg):
        e = _make_entity("req-1", "requirement", "Login flow",
                         {"title": "Login flow", "status": "requested"})
        kg.add_entity(e)

        result = kg.tombstone_entity("req-1", reason="superseded by req-2")

        assert result is True
        after = kg.get_entity("req-1")
        assert after is not None
        assert "tombstoned_at" in after.properties
        assert "valid_to" in after.properties
        assert after.properties["tombstoned_at"] == after.properties["valid_to"]
        assert after.properties["tombstone_reason"] == "superseded by req-2"
        # add_entity -> version 1; tombstone update -> version 2.
        assert after.version == 2

    def test_tombstone_default_reason_is_empty(self, kg):
        e = _make_entity("req-x", "requirement", "X", {"title": "X"})
        kg.add_entity(e)

        kg.tombstone_entity("req-x")

        after = kg.get_entity("req-x")
        assert after.properties["tombstone_reason"] == ""

    def test_tombstone_returns_false_for_missing_entity(self, kg):
        assert kg.tombstone_entity("does-not-exist") is False

    def test_is_tombstoned(self, kg):
        e = _make_entity("req-2", "requirement", "Export", {"title": "Export"})
        kg.add_entity(e)

        assert kg.is_tombstoned("req-2") is False

        kg.tombstone_entity("req-2")

        assert kg.is_tombstoned("req-2") is True
        # Non-existent entities are not tombstoned.
        assert kg.is_tombstoned("nope") is False

    def test_tombstone_not_physically_deleted(self, kg):
        e = _make_entity("req-3", "requirement", "Audit log", {"title": "Audit log"})
        kg.add_entity(e)
        kg.tombstone_entity("req-3")

        # Still queryable by get_entity.
        assert kg.get_entity("req-3") is not None
        # And still present by type.
        by_type = kg.get_entities_by_type("requirement")
        assert any(ent.id == "req-3" for ent in by_type)

    def test_tombstone_recorded_in_history(self, kg):
        e = _make_entity("req-4", "requirement", "SSO", {"title": "SSO"})
        kg.add_entity(e)
        kg.tombstone_entity("req-4", reason="descoped")

        history = kg.get_entity_history("req-4")
        # created + tombstone (updated) entries.
        assert len(history) == 2
        # Ordered version DESC, so the tombstone entry is first.
        latest = history[0]
        assert latest["change_type"] == "updated"
        assert latest["version"] == 2
        assert "tombstoned_at" in latest["properties"]
        assert latest["properties"]["tombstone_reason"] == "descoped"

    def test_get_active_entities_excludes_tombstoned(self, kg):
        a = _make_entity("req-a", "requirement", "A", {"title": "A"})
        b = _make_entity("req-b", "requirement", "B", {"title": "B"})
        c = _make_entity("risk-c", "risk", "C", {"title": "C"})
        kg.add_entity(a)
        kg.add_entity(b)
        kg.add_entity(c)
        kg.tombstone_entity("req-b")

        # Filter by type.
        active_reqs = kg.get_active_entities(entity_type="requirement")
        active_ids = {ent.id for ent in active_reqs}
        assert active_ids == {"req-a"}
        assert "req-b" not in active_ids

        # No type filter -> all active entities.
        all_active = kg.get_active_entities()
        all_ids = {ent.id for ent in all_active}
        assert "req-a" in all_ids
        assert "risk-c" in all_ids
        assert "req-b" not in all_ids

    def test_get_active_entities_scope_filter(self, kg):
        e1 = _make_entity("req-s1", "requirement", "S1", {"title": "S1"})
        e2 = _make_entity("req-s2", "requirement", "S2", {"title": "S2"})
        kg.add_entity(e1, scope_id="scope-1")
        kg.add_entity(e2, scope_id="scope-2")
        kg.tombstone_entity("req-s1")

        active = kg.get_active_entities(scope_id="scope-1")
        assert [ent.id for ent in active] == []
        active2 = kg.get_active_entities(scope_id="scope-2")
        assert [ent.id for ent in active2] == ["req-s2"]

    def test_get_entity_timeline(self, kg):
        e = _make_entity("req-tl", "requirement", "Timeline",
                         {"title": "Timeline", "status": "requested"})
        kg.add_entity(e)
        kg.tombstone_entity("req-tl", reason="done")

        timeline = kg.get_entity_timeline("req-tl")

        assert timeline["entity_id"] == "req-tl"
        assert timeline["current"] is not None
        assert timeline["current"]["id"] == "req-tl"
        assert timeline["current"]["version"] == 2
        assert timeline["is_tombstoned"] is True
        assert len(timeline["history"]) == 2
        # History ordered version DESC.
        assert timeline["history"][0]["version"] == 2
        assert timeline["history"][1]["version"] == 1

    def test_get_entity_timeline_missing_entity(self, kg):
        timeline = kg.get_entity_timeline("ghost")

        assert timeline["entity_id"] == "ghost"
        assert timeline["current"] is None
        assert timeline["is_tombstoned"] is False
        assert timeline["history"] == []


# ---------------------------------------------------------------------------
# Round-trip tests for new entity types
# ---------------------------------------------------------------------------

class TestProjectEntityRoundTrip:
    def test_requirement_round_trip(self, kg):
        e = _make_entity(
            "requirement-1", "requirement", "OAuth login",
            {"title": "OAuth login", "description": "Support OAuth2",
             "status": "requested", "priority": "must",
             "requested_by": "stakeholder-1"},
        )
        kg.add_entity(e)

        got = kg.get_entity("requirement-1")
        assert got is not None
        assert got.type == "requirement"
        assert got.name == "OAuth login"
        assert got.properties["status"] == "requested"
        assert got.properties["priority"] == "must"

    def test_risk_round_trip(self, kg):
        e = _make_entity(
            "risk-1", "risk", "Schedule slip",
            {"title": "Schedule slip", "description": "Key dev on leave",
             "severity": "high", "likelihood": "probable",
             "mitigation": "Backfill contractor", "status": "identified"},
        )
        kg.add_entity(e)

        got = kg.get_entity("risk-1")
        assert got is not None
        assert got.type == "risk"
        assert got.properties["severity"] == "high"
        assert got.properties["likelihood"] == "probable"

    def test_action_item_round_trip(self, kg):
        e = _make_entity(
            "action-1", "action-item", "Write design doc",
            {"title": "Write design doc", "assignee": "alice",
             "due_date": "2026-09-01T00:00:00Z", "status": "open",
             "priority": "high"},
        )
        kg.add_entity(e)

        got = kg.get_entity("action-1")
        assert got is not None
        assert got.type == "action-item"
        assert got.properties["assignee"] == "alice"
        assert got.properties["status"] == "open"

    def test_release_round_trip(self, kg):
        e = _make_entity(
            "release-1", "release", "v1.2.0",
            {"version": "1.2.0", "date": "2026-08-15T00:00:00Z",
             "changes": ["feat: export", "fix: crash"], "status": "planned"},
        )
        kg.add_entity(e)

        got = kg.get_entity("release-1")
        assert got is not None
        assert got.type == "release"
        assert got.properties["version"] == "1.2.0"
        assert got.properties["changes"] == ["feat: export", "fix: crash"]

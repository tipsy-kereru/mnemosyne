"""Contract §6 — work-slack is invisible to every graph read path.

INV-1 is the primary guarantee: Slack content never reaches ``entities``
or ``relations``, which is what makes the read surfaces this program
cannot edit (serve, mcp, retrieval, wiki) safe by construction.

The remaining tests inject a ``work-slack`` entity *directly* to prove
the graph-side predicate is a real guard rather than dead code — if a
promotion path is ever added, these are the tests that keep the default
answer "denied".
"""

from __future__ import annotations

from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph
from mnemosyne.integrations.slack.identity import SOURCE_CHANNEL
from mnemosyne.integrations.slack.store import SlackStore

from .conftest import CHANNEL_ID, SCOPE_ID, SOURCE_ID, TEAM_ID, build_fixture, make_engine


def make_entity(kg, name, channel, entity_type="note"):
    return kg.add_entity(
        Entity(
            id=f"e-{name}",
            type=entity_type,
            name=name,
            properties={"body": f"{name} body"},
            created_at="",
            updated_at="",
        ),
        source_channel=channel,
    )


def test_slack_sync_writes_nothing_into_the_graph(db_path):
    """T-ISO-1 (core, INV-1)."""
    kg = KnowledgeGraph(str(db_path))
    store = SlackStore(db_path)
    store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID)
    result = make_engine(store, build_fixture()).sync(SOURCE_ID)
    assert result.ingested == 12

    for table in ("entities", "relations"):
        count = kg.conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE source_channel = ?",
            (SOURCE_CHANNEL,),
        ).fetchone()[0]
        assert count == 0, f"{table} must never hold Slack content"

    assert kg.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
    assert store.conn.execute(
        "SELECT COUNT(*) FROM slack_message"
    ).fetchone()[0] == 12

    store.close()
    kg.close()


def test_unscoped_search_excludes_isolated_entities(db_path):
    """T-ISO-2: silent exclusion — the query never named work-slack."""
    kg = KnowledgeGraph(str(db_path))
    make_entity(kg, "visible", "manual")
    make_entity(kg, "secret", SOURCE_CHANNEL)

    names = {r["name"] for r in kg.query("search:body")["results"]}
    assert names == {"visible"}

    assert kg.query("search:secret")["results"] == []
    kg.close()


def test_explicit_isolated_channel_request_is_refused(db_path):
    """T-ISO-3 / R25: naming it earns an explicit denial, not silence."""
    kg = KnowledgeGraph(str(db_path))
    make_entity(kg, "secret", SOURCE_CHANNEL)

    result = kg.query(f"entity:note[secret]@channel:{SOURCE_CHANNEL}")
    assert result["error"] == "slack_isolated"
    assert result["count"] == 0
    assert result["results"] == []
    assert "mnemosyne-slack" in result["hint"]
    kg.close()


def test_visible_channel_filter_still_works(db_path):
    """The guard must not break ordinary channel filtering."""
    kg = KnowledgeGraph(str(db_path))
    make_entity(kg, "coded", "code")
    assert kg.query("search:coded@channel:code")["count"] == 1
    kg.close()


def test_entity_and_relation_queries_exclude_isolated(db_path):
    kg = KnowledgeGraph(str(db_path))
    make_entity(kg, "visible", "manual")
    make_entity(kg, "secret", SOURCE_CHANNEL)

    result = kg.query("entity:note[secret]")
    assert result["count"] == 0
    assert kg.query("entity:note[visible]")["count"] == 1
    kg.close()


def test_path_query_routes_around_isolated_nodes(db_path):
    """T-ISO-4: passing through isolated content would itself leak it."""
    from mnemosyne.graph.knowledge_graph import Relation

    kg = KnowledgeGraph(str(db_path))
    make_entity(kg, "alpha", "manual")
    make_entity(kg, "bridge", SOURCE_CHANNEL)
    make_entity(kg, "omega", "manual")
    for i, (src, dst) in enumerate((("e-alpha", "e-bridge"), ("e-bridge", "e-omega"))):
        kg.add_relation(
            Relation(
                id=f"r{i}", source_id=src, target_id=dst,
                relation_type="links", properties={}, created_at="",
            ),
            source_channel="manual",
        )

    assert kg.query("path:alpha,omega")["error"] == "No path found"

    # A route that avoids the isolated node is still found.
    make_entity(kg, "detour", "manual")
    for i, (src, dst) in enumerate((("e-alpha", "e-detour"), ("e-detour", "e-omega"))):
        kg.add_relation(
            Relation(
                id=f"r-d{i}", source_id=src, target_id=dst,
                relation_type="links", properties={}, created_at="",
            ),
            source_channel="manual",
        )
    assert kg.query("path:alpha,omega")["path"] == ["e-alpha", "e-detour", "e-omega"]
    kg.close()


def test_stats_do_not_count_isolated_entities(db_path):
    """T-ISO-5: not even as a separate figure — a count discloses existence."""
    kg = KnowledgeGraph(str(db_path))
    make_entity(kg, "visible", "manual")
    make_entity(kg, "secret", SOURCE_CHANNEL, entity_type="bug")

    stats = kg.get_stats()
    assert stats["entities"] == 1
    assert stats["by_type"] == {"note": 1}
    assert "bug" not in stats["by_type"]
    kg.close()


def test_direct_accessors_exclude_isolated_entities(db_path):
    """T-ISO-6: get_entity, get_entities_by_type, get_active_entities."""
    kg = KnowledgeGraph(str(db_path))
    make_entity(kg, "visible", "manual")
    make_entity(kg, "secret", SOURCE_CHANNEL)

    assert kg.get_entity("e-secret") is None
    assert kg.get_entity("e-visible") is not None
    assert [e.name for e in kg.get_entities_by_type("note")] == ["visible"]
    assert [e.name for e in kg.get_active_entities()] == ["visible"]
    assert kg._find_entity_id_by_name("secret") is None
    assert kg._find_entity_id_by_name("visible") == "e-visible"
    kg.close()


def test_scope_stats_exclude_isolated_entities(db_path):
    kg = KnowledgeGraph(str(db_path))
    scope = kg.create_scope("project", "proj")
    kg.add_entity(
        Entity(id="e-vis", type="note", name="vis", properties={},
               created_at="", updated_at=""),
        scope_id=scope.id, source_channel="manual",
    )
    kg.add_entity(
        Entity(id="e-iso", type="note", name="iso", properties={},
               created_at="", updated_at=""),
        scope_id=scope.id, source_channel=SOURCE_CHANNEL,
    )

    counts = kg.get_stats()["scopes"]["entity_counts_per_scope"]
    assert counts["proj"]["entity_count"] == 1
    assert kg.query("scope:proj")["scope"]["entity_count"] == 1
    kg.close()


def test_mnemosyne_query_cli_exits_two_for_an_isolated_channel(db_path, capsys):
    """T-CLI-6: the graph CLI signals the denial, not an empty success."""
    from mnemosyne.graph.cli import main as query_main

    kg = KnowledgeGraph(str(db_path))
    make_entity(kg, "secret", SOURCE_CHANNEL)
    kg.close()

    code = query_main([
        "--db-path", str(db_path),
        "--query", f"search:secret@channel:{SOURCE_CHANNEL}",
    ])
    assert code == 2
    assert "slack_isolated" in capsys.readouterr().out

    assert query_main(["--db-path", str(db_path), "--query", "search:secret"]) == 0


def test_the_slack_store_still_returns_its_own_content(db_path):
    """T-ISO-7: isolation must not amount to losing the data."""
    kg = KnowledgeGraph(str(db_path))
    store = SlackStore(db_path)
    store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID)
    make_engine(store, build_fixture()).sync(SOURCE_ID)

    assert len(store.list_messages(SOURCE_ID, limit=100)) == 12
    hits = store.search_messages(SOURCE_ID, "reply 4")
    assert len(hits) == 3
    store.close()
    kg.close()

"""Synthetic lifecycle contracts: current answers, recoverability and ordering."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph
from mnemosyne.graph.lifecycle import LifecycleError, LifecycleStore
from mnemosyne.graph.lifecycle_wiki import read_current_wiki, rebuild_wiki


@pytest.fixture
def graph(tmp_path):
    kg = KnowledgeGraph(str(tmp_path / "knowledge.db"))
    yield kg
    kg.close()


def token(source="meeting-1", revision=1, content="A", **extra):
    return {
        "source_id": source,
        "revision": revision,
        "source_version": f"version-{revision}",
        "content_hash": content,
        "extractor_version": "extractor-1",
        "ontology_version": "rules-1",
        **extra,
    }


def observe(kg, t, **extra):
    return LifecycleStore(kg).apply(
        {
            "action": "observe",
            **t,
            "location": f"app://{t['source_id']}",
            "kind": "meeting",
            "source_channel": "meeting-test",
            "scope_id": None,
            **extra,
        }
    )


def entity(identity="project", **properties):
    return {"id": identity, "name": identity, "type": "project", "properties": properties}


def relation(identity="depends", source="project", target="task", **properties):
    return {
        "id": identity,
        "source_id": source,
        "target_id": target,
        "relation_type": "depends_on",
        "properties": properties,
    }


def replace(kg, t, entities, relations=None, **extra):
    req = {
        "action": "replace",
        **t,
        "job_id": f"{t['source_id']}-{t['revision']}",
        "complete": True,
        "entities": entities,
        "relations": relations or [],
        "checkpoint": {"cursor": t["revision"]},
        **extra,
    }
    return LifecycleStore(kg).apply(req)


def source(kg, t, entities, relations=None, **extra):
    observe(kg, t, **extra)
    return replace(kg, t, entities, relations)


def change(kg, action, identity="project", kind="entity", scope=None, **extra):
    store = LifecycleStore(kg)
    generation = store.status()["generation"]
    approval_id = f"approval-{generation}-{action}"
    store.apply(
        {
            "action": "approve",
            "approval_id": approval_id,
            "actor": "owner",
            "expected_generation": generation,
            "change": {
                "action": action,
                "target_kind": kind,
                "target_id": identity,
                "scope_id": scope,
                **extra,
            },
        }
    )
    return store.apply(
        {"action": "execute", "approval_id": approval_id, "actor": "owner", "job_id": approval_id}
    )


def test_source_replacement_retracts_only_its_own_support(graph):
    source(
        graph, token(), [entity(status="A", removed="old"), entity("task")], [relation(weight=1)]
    )
    source(graph, token("other"), [entity(shared="retained"), entity("task")], [relation(weight=1)])
    source(graph, token(revision=2, content="B"), [entity(status="B")])
    result = graph.get_entity("project")
    assert result.properties["status"] == "B"
    assert "removed" not in result.properties
    assert result.properties["shared"] == "retained"
    assert graph.get_relation("depends") is not None
    assert graph.get_entity("task") is not None
    observe(graph, token("other", 2, "deleted"))
    LifecycleStore(graph).apply(
        {
            "action": "delete",
            **token("other", 2, "deleted"),
            "job_id": "delete-other",
            "checkpoint": {"cursor": 2},
            "deletion": {"kind": "explicit"},
        }
    )
    assert graph.get_relation("depends") is None
    assert graph.get_entity("task") is None
    assert graph.get_entity("project").properties["status"] == "B"
    assert "shared" not in graph.get_entity("project").properties
    assert graph.get_entity_history("task")


def test_reversion_retries_reverse_order_and_late_extraction(graph):
    a, b, again = token(), token(revision=2, content="B"), token(revision=3, content="A")
    source(graph, a, [entity(status="A")])
    observe(graph, b)
    observe(graph, again)
    with pytest.raises(LifecycleError, match="stale"):
        replace(graph, b, [entity(status="B")])
    with pytest.raises(LifecycleError, match="stale"):
        observe(graph, b)
    replace(graph, again, [entity(status="A", returned=True)])
    assert graph.get_entity("project").properties["returned"] is True
    assert replace(graph, again, [entity(status="A", returned=True)])["status"] == "duplicate"
    assert replace(graph, a, [entity(status="A")])["status"] == "duplicate"
    assert graph.get_entity("project").properties["returned"] is True
    with pytest.raises(LifecycleError, match="job_id"):
        replace(graph, again, [entity(status="wrong")])
    with pytest.raises(LifecycleError, match="cannot be rewritten"):
        replace(graph, again, [entity(status="wrong")], job_id="different-job")
    assert (
        graph.conn.execute("SELECT COUNT(*) FROM lifecycle_evidence WHERE active=1").fetchone()[0]
        == 1
    )


def test_rule_fence_and_identical_hash_are_not_apply_cache(graph):
    source(graph, token(), [entity(status="A")])
    newer = token(revision=2, extractor_version="extractor-2", ontology_version="rules-2")
    observe(graph, newer)
    with pytest.raises(LifecycleError, match="stale"):
        replace(graph, token(revision=2), [entity(status="wrong")])
    replace(graph, newer, [entity(status="new-rule-result")])
    assert graph.get_entity("project").properties["status"] == "new-rule-result"
    with pytest.raises(LifecycleError, match="metadata"):
        observe(graph, {**newer, "content_hash": "different"})


@pytest.mark.parametrize("failure", ["partial", "missing-endpoint", "duplicate-entity"])
def test_invalid_extraction_preserves_old_answers_and_checkpoint(graph, failure):
    source(graph, token(), [entity(status="old")])
    current = token(revision=2, content="B")
    observe(graph, current)
    entities, relations, extra = [entity(status="bad")], [], {}
    if failure == "partial":
        extra["complete"] = False
    elif failure == "missing-endpoint":
        relations = [relation()]
    else:
        entities.append(entity(status="duplicate"))
    with pytest.raises(LifecycleError):
        replace(graph, current, entities, relations, **extra)
    assert graph.get_entity("project").properties["status"] == "old"
    state = graph.conn.execute(
        "SELECT state,applied_revision,checkpoint FROM lifecycle_sources"
    ).fetchone()
    assert state["state"] == "pending"
    assert state["applied_revision"] == 1
    assert json.loads(state["checkpoint"]) == {"cursor": 1}


@pytest.mark.parametrize(
    "proof",
    [
        {},
        {"kind": "reconciliation", "complete": False, "scope": "vault", "boundary": "scan-2"},
        {"kind": "reconciliation", "complete": True, "scope": "vault"},
        {"kind": "reconciliation", "complete": True, "scope": "wrong", "boundary": "scan-2"},
    ],
)
def test_inaccessible_or_incomplete_listing_never_deletes(graph, proof):
    source(graph, token(), [entity(status="kept")], scope_id="vault")
    t = token(revision=2, content="deleted")
    observe(graph, t, scope_id="vault")
    with pytest.raises(LifecycleError):
        LifecycleStore(graph).apply(
            {"action": "delete", **t, "job_id": "delete", "checkpoint": {}, "deletion": proof}
        )
    assert graph.get_entity("project").properties["status"] == "kept"


def test_confirmed_reconciliation_and_same_path_new_identity(graph):
    source(
        graph, token(), [entity(status="old")], scope_id="vault", location="file:///vault/note.md"
    )
    t = token(revision=2, content="deleted")
    observe(graph, t, scope_id="vault", location="file:///vault/note.md")
    LifecycleStore(graph).apply(
        {
            "action": "delete",
            **t,
            "job_id": "delete",
            "checkpoint": {},
            "deletion": {
                "kind": "reconciliation",
                "complete": True,
                "scope": "vault",
                "boundary": "completed-scan-2",
            },
        }
    )
    assert graph.get_entity("project") is None
    source(
        graph,
        token("new-original"),
        [entity(status="new")],
        scope_id="vault",
        location="file:///vault/note.md",
    )
    assert graph.get_entity("project").properties["evidence"][0]["source_id"] == "new-original"


def test_correction_is_separate_survives_move_restart_rebuild_and_retract(graph, tmp_path):
    source(graph, token(), [entity(status="source-old")])
    corrected = change(
        graph, "correct", property="status", value="approved", effective_scope={"kind": "claim"}
    )
    t = token(revision=2, content="B")
    observe(graph, t, location="app://moved")
    assert replace(graph, t, [entity(status="source-new")])["status"] == "review"
    reopened = KnowledgeGraph(str(graph.db_path))
    try:
        assert reopened.get_entity("project").properties["status"] == "approved"
        stored = reopened.conn.execute(
            "SELECT payload FROM lifecycle_evidence WHERE active=1"
        ).fetchone()[0]
        assert json.loads(stored)["properties"]["status"] == "source-new"
        assert reopened.conn.execute("SELECT 1 FROM lifecycle_reviews").fetchone()
        rebuild_wiki(reopened, tmp_path / "wiki")
        assert '"status": "approved"' in read_current_wiki(reopened, tmp_path / "wiki")
        change(reopened, "retract", record_id=corrected["record_id"])
        assert reopened.get_entity("project").properties["status"] == "source-new"
        with pytest.raises(LifecycleError, match="dirty"):
            read_current_wiki(reopened, tmp_path / "wiki")
    finally:
        reopened.close()


@pytest.mark.parametrize("action", ["archive", "exclude"])
def test_visibility_restore_uses_current_evidence_not_archived_value(graph, tmp_path, action):
    source(graph, token(), [entity(status="A"), entity("task")], [relation()])
    hidden = change(graph, action)
    assert "project" not in {row["id"] for row in graph.query("search:project")["results"]}
    assert graph.get_relation("depends") is None
    source(
        graph, token(revision=2, content="B"), [entity(status="B"), entity("task")], [relation()]
    )
    assert graph.get_entity("project") is None
    rebuild_wiki(graph, tmp_path / "wiki")
    assert '"status": "B"' not in read_current_wiki(graph, tmp_path / "wiki")
    change(graph, "restore", record_id=hidden["record_id"])
    assert graph.get_entity("project").properties["status"] == "B"
    assert graph.get_relation("depends") is not None
    assert (
        graph.conn.execute(
            "SELECT COUNT(*) FROM lifecycle_evidence WHERE target_id='project'"
        ).fetchone()[0]
        == 2
    )


def test_source_exclusion_leaves_other_support_and_persists_move(graph):
    source(graph, token(), [entity(secret="private", common="yes")])
    source(graph, token("other"), [entity(common="yes")])
    hidden = change(graph, "exclude", identity="meeting-1", kind="source")
    assert "secret" not in graph.get_entity("project").properties
    t = token(revision=2, content="B")
    observe(graph, t, location="app://new-location")
    replace(graph, t, [entity(secret="new-private", common="yes")])
    assert "secret" not in graph.get_entity("project").properties
    change(graph, "restore", identity="meeting-1", kind="source", record_id=hidden["record_id"])
    assert graph.get_entity("project").properties["secret"] == "new-private"


def test_withdrawal_does_not_restore_deleted_evidence(graph):
    source(graph, token(), [entity(status="A")])
    hidden = change(graph, "archive")
    t = token(revision=2, content="deleted")
    observe(graph, t)
    LifecycleStore(graph).apply(
        {
            "action": "delete",
            **t,
            "job_id": "delete",
            "checkpoint": {},
            "deletion": {"kind": "explicit"},
        }
    )
    change(graph, "restore", record_id=hidden["record_id"])
    assert graph.get_entity("project") is None


def test_approval_scope_actor_generation_and_replay(graph):
    source(graph, token(), [entity(status="A")])
    store = LifecycleStore(graph)
    req = {
        "action": "approve",
        "approval_id": "approval",
        "actor": "owner",
        "expected_generation": store.status()["generation"],
        "change": {
            "action": "archive",
            "target_kind": "entity",
            "target_id": "project",
            "scope_id": "wrong",
        },
    }
    with pytest.raises(LifecycleError, match="scope"):
        store.apply(req)
    req["change"]["scope_id"] = None
    store.apply(req)
    execute = {
        "action": "execute",
        "approval_id": "approval",
        "actor": "attacker",
        "job_id": "execute",
    }
    with pytest.raises(LifecycleError, match="actor"):
        store.apply(execute)
    observe(graph, token(revision=2, content="B"))
    with pytest.raises(LifecycleError, match="stale"):
        store.apply({**execute, "actor": "owner"})
    assert graph.get_entity("project") is not None


def test_correction_supersession_keeps_auditable_chain(graph):
    source(graph, token(), [entity(status="A")])
    first = change(
        graph, "correct", property="status", value="B", effective_scope={"kind": "claim"}
    )
    second = change(
        graph,
        "correct",
        property="status",
        value="C",
        effective_scope={"kind": "claim"},
        supersedes=first["record_id"],
    )
    assert graph.get_entity("project").properties["status"] == "C"
    change(graph, "retract", record_id=second["record_id"])
    assert graph.get_entity("project").properties["status"] == "A"
    assert graph.conn.execute("SELECT COUNT(*) FROM lifecycle_changes").fetchone()[0] == 3


def test_transaction_fault_does_not_publish_half_graph_or_completed_job(graph):
    source(graph, token(), [entity(status="A")])
    t = token(revision=2, content="B")
    observe(graph, t)
    before = LifecycleStore(graph).status()
    graph.conn.execute(
        "CREATE TRIGGER injected_failure BEFORE INSERT ON lifecycle_jobs WHEN NEW.job_id='meeting-1-2' BEGIN SELECT RAISE(ABORT, 'injected crash'); END"
    )
    graph.conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected crash"):
        replace(graph, t, [entity(status="B"), entity("new-target")])
    assert LifecycleStore(graph).status() == before
    assert graph.get_entity("project").properties["status"] == "A"
    assert graph.get_entity("new-target") is None
    assert graph.conn.execute("SELECT applied_revision FROM lifecycle_sources").fetchone()[0] == 1
    assert graph.conn.execute("SELECT writing FROM lifecycle_state").fetchone()[0] == 0
    graph.conn.execute("DROP TRIGGER injected_failure")
    graph.conn.commit()
    replace(graph, t, [entity(status="B"), entity("new-target")])
    assert graph.get_entity("new-target") is not None


def test_wiki_failure_recovery_and_stale_snapshot_denial(graph, tmp_path, monkeypatch):
    source(graph, token(), [entity(status="A")])
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("# Old index\n\nUser-maintained note\n", encoding="utf-8")
    rebuild_wiki(graph, wiki)
    archived_index = next((wiki / ".lifecycle-history").rglob("index.md"))
    assert "User-maintained note" in archived_index.read_text(encoding="utf-8")
    assert "User-maintained note" not in read_current_wiki(graph, wiki)
    source(graph, token(revision=2, content="B"), [entity(status="B")])
    from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer

    original = LLMWikiMaintainer._atomic_write

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(LLMWikiMaintainer, "_atomic_write", fail)
    with pytest.raises(OSError, match="disk full"):
        rebuild_wiki(graph, wiki)
    assert graph.get_entity("project").properties["status"] == "B"
    with pytest.raises(LifecycleError, match="dirty"):
        read_current_wiki(graph, wiki)
    monkeypatch.setattr(LLMWikiMaintainer, "_atomic_write", original)
    rebuild_wiki(graph, wiki)
    assert '"status": "B"' in read_current_wiki(graph, wiki)
    assert '"status": "A"' not in read_current_wiki(graph, wiki)


def test_wiki_racing_graph_commit_is_not_marked_clean(graph, tmp_path, monkeypatch):
    source(graph, token(), [entity(status="A")])
    from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer

    original = LLMWikiMaintainer._atomic_write

    def concurrent_change(path, content):
        original(path, content)
        source(graph, token(revision=2, content="B"), [entity(status="B")])

    monkeypatch.setattr(LLMWikiMaintainer, "_atomic_write", concurrent_change)
    with pytest.raises(LifecycleError, match="changed"):
        rebuild_wiki(graph, tmp_path / "wiki")
    assert LifecycleStore(graph).status()["wiki_dirty"] is True
    assert graph.get_entity("project").properties["status"] == "B"


def test_reopened_graph_does_not_traverse_excluded_intermediate(graph):
    source(
        graph,
        token(),
        [entity(), entity("middle"), entity("task")],
        [relation("first", target="middle"), relation("last", source="middle")],
    )
    reader = KnowledgeGraph(str(graph.db_path))
    try:
        assert reader.query("path:project,task")["length"] == 2
        change(graph, "exclude", identity="middle")
        assert reader.query("path:project,task")["error"] == "No path found"
    finally:
        reader.close()


def test_concurrent_connections_cannot_overwrite_newer_observation(graph):
    observe(graph, token())

    def apply_revision(revision):
        kg = KnowledgeGraph(str(graph.db_path))
        try:
            t = token(revision=revision, content=str(revision))
            try:
                observe(kg, t)
                replace(kg, t, [entity(status=str(revision))])
            except LifecycleError:
                pass
        finally:
            kg.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(apply_revision, [2, 3]))
    assert graph.get_entity("project").properties["status"] == "3"


def test_user_notes_and_visibility_restore_from_database_backup(graph, tmp_path):
    t = token("user-note-1")
    observe(graph, t, kind="user-note")
    replace(graph, t, [entity(status="A")], note_text="Original user-authored note")
    t2 = token("user-note-1", 2, "B")
    observe(graph, t2, kind="user-note")
    with pytest.raises(LifecycleError, match="approval"):
        replace(graph, t2, [entity(status="B")], note_text="Revised user-authored note")
    change(
        graph,
        "revise-note",
        identity="user-note-1",
        kind="source",
        replacement={
            **t2,
            "complete": True,
            "entities": [entity(status="B")],
            "relations": [],
            "checkpoint": {"cursor": 2},
            "note_text": "Revised user-authored note",
        },
    )
    correction = change(
        graph, "correct", property="status", value="approved", effective_scope={"kind": "claim"}
    )
    hidden = change(graph, "exclude")
    backup = sqlite3.connect(str(tmp_path / "restored.db"))
    graph.conn.backup(backup)
    backup.close()
    restored = KnowledgeGraph(str(tmp_path / "restored.db"))
    try:
        assert restored.get_entity("project") is None
        change(restored, "restore", record_id=hidden["record_id"])
        assert restored.get_entity("project").properties["status"] == "approved"
        change(restored, "retract", record_id=correction["record_id"])
        assert restored.get_entity("project").properties["status"] == "B"
        notes = restored.conn.execute(
            "SELECT note_text FROM lifecycle_versions ORDER BY revision"
        ).fetchall()
        assert [r[0] for r in notes] == [
            "Original user-authored note",
            "Revised user-authored note",
        ]
        assert (
            restored.conn.execute("SELECT source_id FROM lifecycle_sources").fetchone()[0]
            == "user-note-1"
        )
    finally:
        restored.close()


def test_pre_lifecycle_migration_backups_before_schema_change(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE entities (id TEXT PRIMARY KEY,type TEXT NOT NULL,name TEXT NOT NULL,properties TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,version INTEGER DEFAULT 1)"
    )
    conn.execute(
        "INSERT INTO entities VALUES ('legacy','project','legacy','{\"old\":true}','2020','2020',1)"
    )
    conn.commit()
    conn.close()
    kg = KnowledgeGraph(str(path))
    try:
        assert kg.get_entity("legacy").properties == {"old": True}
        original = sqlite3.connect(kg.lifecycle_backup_path)
        try:
            assert original.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert (
                original.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='lifecycle_state'"
                ).fetchone()
                is None
            )
            assert "scope_id" not in [r[1] for r in original.execute("PRAGMA table_info(entities)")]
            assert (
                original.execute("SELECT properties FROM entities").fetchone()[0] == '{"old":true}'
            )
        finally:
            original.close()
        source(kg, token(), [entity("legacy", new=True)])
        source(kg, token(revision=2, content="empty"), [])
        assert kg.get_entity("legacy").properties["old"] is True
        assert "new" not in kg.get_entity("legacy").properties
        assert (
            kg.get_entity("legacy").properties["evidence"][0]["source_id"] == "legacy:unattributed"
        )
    finally:
        kg.close()
    reopened = KnowledgeGraph(str(path))
    assert reopened.lifecycle_backup_path is None
    reopened.close()


def test_legacy_write_cannot_resurrect_excluded_record(graph):
    source(graph, token(), [entity(status="A")])
    change(graph, "exclude")
    with pytest.raises((LifecycleError, sqlite3.IntegrityError)):
        graph.add_entity(Entity("project", "project", "project", {"status": "bad"}, "now", "now"))
    graph.conn.rollback()
    assert graph.get_entity("project") is None


def test_scope_collision_and_isolated_channel_rejected(graph):
    source(graph, token(), [entity(status="A")], scope_id="one")
    observe(graph, token("other"), scope_id="two")
    with pytest.raises(LifecycleError, match="scope"):
        replace(graph, token("other"), [entity(status="B")])
    with pytest.raises(LifecycleError, match="isolated"):
        observe(graph, token("slack"), source_channel="work-slack")
    assert graph.get_entity("project").properties["status"] == "A"


@pytest.mark.parametrize("crash_point", ["before-commit", "after-commit", "wiki-render"])
def test_hard_process_exit_recovers_without_manual_lock_cleanup(graph, tmp_path, crash_point):
    import os
    import subprocess
    import sys

    source(graph, token(), [entity(status="A")])
    t = token(revision=2, content="B")
    observe(graph, t)
    request = {
        "action": "replace",
        **t,
        "job_id": "crash-job",
        "complete": True,
        "entities": [entity(status="B")],
        "relations": [],
        "checkpoint": {"cursor": 2},
    }
    code = """
import json, os, sys
from mnemosyne.graph.knowledge_graph import KnowledgeGraph
from mnemosyne.graph.lifecycle import LifecycleStore
from mnemosyne.graph.lifecycle_wiki import rebuild_wiki
from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer
kg = KnowledgeGraph(sys.argv[1])
store = LifecycleStore(kg)
req = json.loads(sys.argv[2])
phase = sys.argv[3]
if phase == 'before-commit':
    original = store._finish_source
    def fail(*args):
        original(*args)
        os._exit(73)
    store._finish_source = fail
store.apply(req)
if phase == 'wiki-render':
    original = LLMWikiMaintainer._atomic_write
    def fail(path, content):
        original(path, content)
        os._exit(73)
    LLMWikiMaintainer._atomic_write = staticmethod(fail)
    rebuild_wiki(kg, sys.argv[4])
os._exit(73)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(graph.db_path),
            json.dumps(request),
            crash_point,
            str(tmp_path / "wiki"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 73, result.stderr
    expected = "A" if crash_point == "before-commit" else "B"
    assert graph.get_entity("project").properties["status"] == expected
    result = LifecycleStore(graph).apply(request)
    assert result["status"] == ("applied" if crash_point == "before-commit" else "duplicate")
    rebuild_wiki(graph, tmp_path / "wiki")
    assert '"status": "B"' in read_current_wiki(graph, tmp_path / "wiki")


def test_wiki_from_different_database_is_not_current_evidence(graph, tmp_path):
    source(graph, token(), [entity(status="private")])
    rebuild_wiki(graph, tmp_path / "wiki")
    other = KnowledgeGraph(str(tmp_path / "other.db"))
    try:
        source(other, token(), [entity(status="public")])
        rebuild_wiki(other, tmp_path / "other-wiki")
        assert (
            LifecycleStore(other).status()["generation"]
            == LifecycleStore(graph).status()["generation"]
        )
        with pytest.raises(LifecycleError, match="database"):
            read_current_wiki(other, tmp_path / "wiki")
    finally:
        other.close()


def test_relation_correction_and_visibility_are_independent(graph):
    source(graph, token(), [entity(), entity("task")], [relation(weight=1)])
    correction = change(
        graph,
        "correct",
        identity="depends",
        kind="relation",
        property="weight",
        value=2,
        effective_scope={"kind": "claim"},
    )
    source(graph, token(revision=2, content="B"), [entity(), entity("task")], [relation(weight=3)])
    assert graph.get_relation("depends").properties["weight"] == 2
    hidden = change(graph, "exclude", identity="depends", kind="relation")
    assert graph.get_relation("depends") is None
    assert graph.get_entity("project") is not None
    change(graph, "restore", identity="depends", kind="relation", record_id=hidden["record_id"])
    change(graph, "retract", identity="depends", kind="relation", record_id=correction["record_id"])
    assert graph.get_relation("depends").properties["weight"] == 3


def test_legacy_changes_invalidate_bound_approval(graph):
    graph.add_entity(Entity("legacy", "project", "legacy", {"status": "A"}, "now", "now"))
    store = LifecycleStore(graph)
    store.apply(
        {
            "action": "approve",
            "approval_id": "a",
            "actor": "owner",
            "expected_generation": store.status()["generation"],
            "change": {
                "action": "archive",
                "target_kind": "entity",
                "target_id": "legacy",
                "scope_id": None,
            },
        }
    )
    item = graph.get_entity("legacy")
    item.properties["status"] = "B"
    graph.update_entity(item)
    with pytest.raises(LifecycleError, match="stale"):
        store.apply(
            {"action": "execute", "approval_id": "a", "actor": "owner", "job_id": "old-approval"}
        )
    assert graph.get_entity("legacy").properties["status"] == "B"


def test_review_recomputed_from_current_not_historical_disagreement(graph):
    source(graph, token(), [entity(status="A")])
    change(graph, "correct", property="status", value="B", effective_scope={"kind": "claim"})
    assert graph.get_entity("project").properties["review_required"] is True
    source(graph, token(revision=2, content="B"), [entity(status="B")])
    assert graph.get_entity("project").properties["review_required"] is False
    assert LifecycleStore(graph).inspect("source", "meeting-1")["source"]["state"] == "applied"


def test_multiple_visibility_records_need_explicit_independent_restoration(graph):
    source(graph, token(), [entity(status="A")])
    archived = change(graph, "archive")
    excluded = change(graph, "exclude")
    change(graph, "restore", record_id=archived["record_id"])
    assert graph.get_entity("project") is None
    change(graph, "restore", record_id=excluded["record_id"])
    assert graph.get_entity("project").properties["status"] == "A"


def test_archive_cannot_smuggle_retraction_of_another_record(graph):
    source(graph, token(), [entity(), entity("task")])
    hidden = change(graph, "exclude")
    with pytest.raises(LifecycleError, match="record_id"):
        change(graph, "archive", identity="task", record_id=hidden["record_id"])
    assert graph.get_entity("project") is None
    assert graph.get_entity("task") is not None


def test_unversioned_ingestion_refused_before_external_processing(graph, tmp_path):
    from mnemosyne.ingest.ingester import Ingester
    from unittest.mock import Mock

    source(graph, token(), [entity(status="A")])
    external = Mock(side_effect=AssertionError("external processing must not run"))
    ingester = Ingester(db_path=graph.db_path, raw_root=tmp_path / "raw", llm_bridge=external)
    try:
        with pytest.raises(LifecycleError, match="versioned evidence"):
            ingester.add("https://example.invalid/private")
        with pytest.raises(LifecycleError, match="versioned evidence"):
            ingester.add("", text="private content")
    finally:
        ingester.close()
    assert graph.get_entity("project").properties["status"] == "A"


def test_hybrid_memory_cache_obeys_other_connection_visibility_change(graph, monkeypatch):
    from mnemosyne.retrieval.engine import RetrievalEngine
    from tests.test_retrieval_cache import _make_queryable_engine

    source(graph, token(), [entity("alpha", status="A")])
    reader = KnowledgeGraph(str(graph.db_path))
    try:
        engine, _, _ = _make_queryable_engine(monkeypatch, reader.conn)
        monkeypatch.setattr(
            engine,
            "_fetch_entity_details",
            lambda rows: RetrievalEngine._fetch_entity_details(engine, rows),
        )
        assert engine.query("alpha")[0].properties["status"] == "A"
        change(
            graph,
            "correct",
            identity="alpha",
            property="status",
            value="B",
            effective_scope={"kind": "claim"},
        )
        assert engine.query("alpha")[0].properties["status"] == "B"
        change(graph, "exclude", identity="alpha")
        assert engine.query("alpha") == []
    finally:
        reader.close()

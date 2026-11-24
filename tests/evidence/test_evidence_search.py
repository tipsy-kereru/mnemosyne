"""Exact-scope, read-only evidence search against isolated synthetic stores."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from mnemosyne.cli import main as cli_main
from mnemosyne.evidence import evidence_freshness, search_evidence
from mnemosyne.evidence import search as search_mod
from mnemosyne.evidence import store as store_mod
from mnemosyne.graph.knowledge_graph import KnowledgeGraph
from mnemosyne.graph.lifecycle import LifecycleStore
from tests.evidence.helpers import (
    World, build_world, grant, put, tree_state, write_config,
)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return build_world(tmp_path)


def run(world: World, app: str, query: str = "budget", **extra: Any) -> Dict[str, Any]:
    return search_evidence(world.config, {"app_project": app, "query": query, **extra})


def ids(response: Dict[str, Any]) -> set:
    return {r["citation"]["entity_id"] for r in response["results"]}


def fresh(world: World, app: str) -> Dict[str, Any]:
    return evidence_freshness(world.config, {"app_project": app})


def mode_of(db: Path) -> str:
    snap = store_mod.open_snapshot(db, store_mod.Deadline(5000))
    try:
        return snap.mode
    finally:
        store_mod.close_snapshot(snap)


def stored_version(world: World, entity_id: str) -> int:
    conn = sqlite3.connect(world.db)
    try:
        return conn.execute("SELECT version FROM entities WHERE id = ?", (entity_id,)).fetchone()[0]
    finally:
        conn.close()


# --- scoping -----------------------------------------------------------------


@pytest.mark.parametrize(
    "app,expected",
    [
        ("alpha-app", {"a-budget", "a-risk", "a-decision"}),
        ("beta-app", {"b-budget", "b-decision"}),
        ("topic-app", {"t-budget"}),
    ],
)
def test_each_caller_sees_only_its_exact_scope(world, app, expected):
    response = run(world, app, limit=20)
    assert response["status"] == "ok"
    assert ids(response) == expected
    blob = json.dumps(response)
    forbidden = {"BETAONLY", "GLOBALONLY", "CHILDONLY", "SIBLINGONLY", "ISOLATED", "TOMBSTONED"}
    own = {"beta-app": "BETAONLY", "topic-app": "CHILDONLY"}.get(app)
    for marker in forbidden - {own}:
        assert marker not in blob


@pytest.mark.parametrize("marker", ["BETAONLY", "GLOBALONLY", "CHILDONLY", "SIBLINGONLY"])
def test_other_scope_text_is_not_discoverable(world, marker):
    response = run(world, "alpha-app", marker)
    assert response["status"] == "no_matches"
    assert response["results"] == []
    assert response["bounds"]["total_matches"] == 0


def test_scores_and_order_do_not_depend_on_other_scopes(tmp_path):
    quiet = build_world(tmp_path / "quiet", noise=0)
    noisy = build_world(tmp_path / "noisy", noise=60)
    a, b = run(quiet, "alpha-app"), run(noisy, "alpha-app")
    assert a["status"] == b["status"] == "ok" and len(a["results"]) >= 3
    assert [(r["citation"]["id"], r["score"]) for r in a["results"]] == [
        (r["citation"]["id"], r["score"]) for r in b["results"]
    ]


@pytest.mark.parametrize("field", ["scope_id", "scope", "caller", "scope_name", "project"])
def test_request_cannot_name_scope_or_caller(world, field):
    response = run(world, "alpha-app", **{field: world.scopes["beta"]})
    assert response["status"] == "invalid_request"
    assert response["results"] == []


# --- authorization fails closed before retrieval ------------------------------


@pytest.fixture
def no_store_access(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("store opened before authorization")

    monkeypatch.setattr(search_mod, "open_snapshot", boom)


def _config(world: World, grants, caller: str = "meeting-assistant") -> None:
    write_config(world.config, world.db, grants, caller=caller)


def test_unbound_app_project_is_denied(world, no_store_access):
    response = run(world, "unknown-app")
    assert (response["status"], response["reason"]) == ("unauthorized", "unbound")
    assert response["freshness"]["cacheable"] is False


def test_other_callers_grant_is_not_ours(world, no_store_access):
    _config(world, [grant("alpha-app", world.scopes["alpha"], caller="someone-else")])
    assert run(world, "alpha-app")["reason"] == "unbound"


def test_ambiguous_binding_is_denied(world, no_store_access):
    s = world.scopes
    _config(world, [grant("alpha-app", s["alpha"], "g1"), grant("alpha-app", s["beta"], "g2")])
    response = run(world, "alpha-app")
    assert (response["status"], response["reason"]) == ("unauthorized", "ambiguous")


def test_revoked_grant_is_denied_and_replacement_grant_wins(world):
    s = world.scopes
    _config(world, [grant("alpha-app", s["alpha"], "old", "revoked")])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(search_mod, "open_snapshot", lambda *a, **k: pytest.fail("opened"))
        assert run(world, "alpha-app")["reason"] == "revoked"
    _config(world, [grant("alpha-app", s["alpha"], "old", "revoked"),
                    grant("alpha-app", s["beta"], "new")])
    assert ids(run(world, "alpha-app")) == {"b-budget", "b-decision"}


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps([]),
        json.dumps({"version": 2, "store": "x", "effective_caller": "c", "grants": []}),
        json.dumps({"version": 1, "store": "x", "effective_caller": "c", "grants": [], "extra": 1}),
        json.dumps({"version": 1, "store": "x", "effective_caller": "c",
                    "grants": [{"grant_id": "g", "caller": "c", "app_project": "a",
                                "scope_id": None, "status": "active"}]}),
        json.dumps({"version": 1, "store": "x", "effective_caller": "c",
                    "grants": [{"grant_id": "g", "caller": "c", "app_project": "a",
                                "scope_id": "s", "status": "maybe"}]}),
        json.dumps({"version": 1, "store": "x", "effective_caller": "c",
                    "grants": [{"grant_id": "g", "caller": "c", "app_project": "a",
                                "scope_id": "s", "status": "active"}] * 2}),
        '{"version": 1, "version": 1, "store": "x", "effective_caller": "c", "grants": []}',
        json.dumps({"version": 1, "store": "x\u0000y", "effective_caller": "c", "grants": []}),
    ],
)
def test_untrusted_or_invalid_provider_config_denies_everything(world, no_store_access, content):
    world.config.write_text(content, encoding="utf-8")
    response = run(world, "alpha-app")
    assert (response["status"], response["reason"]) == ("unauthorized", "provider_config_invalid")


def test_missing_provider_config_denies(tmp_path, no_store_access):
    response = search_evidence(tmp_path / "absent.json", {"app_project": "a", "query": "x"})
    assert (response["status"], response["reason"]) == ("unauthorized", "provider_config_missing")
    assert search_evidence(None, {"app_project": "a", "query": "x"})["reason"] == "provider_config_missing"


def test_unsupported_field_error_envelope_is_bounded(world, no_store_access):
    request = {"app_project": "alpha-app", "query": "x", **{f"f{i}" * 20: 1 for i in range(5000)}}
    response = search_evidence(world.config, request)
    assert response["status"] == "invalid_request"
    assert len(json.dumps(response).encode()) < 2048


# --- bounds -------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "!!!"},
        {"query": "x" * 257},
        {"query": " ".join(f"t{i}" for i in range(17))},
        {"query": 5},
        {"limit": 0},
        {"limit": 21},
        {"limit": True},
        {"limit": "5"},
        {"max_excerpt_chars": 39},
        {"max_excerpt_chars": 1201},
        {"timeout_ms": 49},
        {"timeout_ms": 10001},
    ],
)
def test_query_and_limit_bounds_are_enforced(world, no_store_access, extra):
    request = {"app_project": "alpha-app", "query": "budget", **extra}
    assert search_evidence(world.config, request)["status"] == "invalid_request"


def test_result_and_excerpt_bounds(tmp_path):
    w = build_world(tmp_path)
    kg = KnowledgeGraph(str(w.db))
    for i in range(30):
        put(kg, f"long-{i}", f"Long {i}", w.scopes["alpha"],
            summary=("filler " * 400) + "budget " + ("tail " * 400))
    kg.close()
    response = run(w, "alpha-app", limit=3, max_excerpt_chars=80)
    assert response["bounds"]["returned"] == 3 and response["bounds"]["truncated"] is True
    assert response["bounds"]["total_matches"] >= 30
    for item in response["results"]:
        assert len(item["excerpt"]) <= 80 and "budget" in item["excerpt"].lower()
    big = run(w, "alpha-app", limit=20, max_excerpt_chars=1200)
    assert len(json.dumps(big, ensure_ascii=False).encode()) <= search_mod.MAX_RESPONSE_BYTES
    assert big["bounds"]["returned"] == len(big["results"]) <= 20


def test_ranking_prefers_denser_and_name_matches(world):
    response = run(world, "alpha-app", "budget approved")
    assert response["results"][0]["citation"]["entity_id"] in {"a-budget", "a-decision"}
    scores = [r["score"] for r in response["results"]]
    assert scores == sorted(scores, reverse=True)


def test_tombstoned_and_isolated_rows_are_excluded(world):
    conn = sqlite3.connect(world.db)
    present = {r[0] for r in conn.execute(
        "SELECT id FROM entities WHERE scope_id = ?", (world.scopes["alpha"],))}
    conn.close()
    assert {"a-gone", "a-slack", "a-budget"} <= present  # they exist; search must hide two
    found = ids(run(world, "alpha-app", limit=20))
    assert "a-budget" in found and not {"a-gone", "a-slack"} & found


def test_cjk_substring_matching(tmp_path):
    w = build_world(tmp_path)
    kg = KnowledgeGraph(str(w.db))
    put(kg, "ko", "예산 회의", w.scopes["alpha"], summary="내부처리 예산 승인")
    kg.close()
    assert "ko" in ids(run(w, "alpha-app", "처리"))


# --- provenance and citations ---------------------------------------------------


def test_lifecycle_provenance_and_stable_citations(world):
    first = run(world, "alpha-app", "approved")
    again = run(world, "alpha-app", "approved")
    assert first["results"] == again["results"]
    top = next(r for r in first["results"] if r["citation"]["entity_id"] == "a-decision")
    assert top["citation"] == {"id": "entity:a-decision", "entity_id": "a-decision",
                               "entity_version": stored_version(world, "a-decision"),
                               "source_ids": ["alpha-meeting"]}
    assert top["provenance"] == [{"source_id": "alpha-meeting", "revision": 1,
                                  "location": "app://alpha-meeting", "locator": "00:12:30"}]
    assert "approved" in top["excerpt"]
    assert "beta-meeting" not in json.dumps(first)


def test_forged_provenance_from_another_scope_is_not_used(world):
    kg = KnowledgeGraph(str(world.db))
    put(kg, "forged", "Forged note", world.scopes["alpha"], summary="plain",
        evidence=[{"source_id": "beta-meeting", "revision": 1, "location": "app://beta-meeting",
                   "excerpt": "zebra secret from beta"}])
    kg.close()
    assert run(world, "alpha-app", "zebra")["status"] == "no_matches"
    forged = next(r for r in run(world, "alpha-app", "plain")["results"]
                  if r["citation"]["entity_id"] == "forged")
    assert forged["provenance"] == [] and forged["citation"]["source_ids"] == []


def test_legacy_source_marker_needs_a_backing_record_in_the_bound_scope(world):
    alpha = world.scopes["alpha"]
    kg = KnowledgeGraph(str(world.db))
    put(kg, "forged-legacy", "Forged legacy", alpha, summary="plainlegacy",
        evidence=[{"source_id": "legacy:unattributed", "revision": 0, "location": "",
                   "excerpt": "quokka forged excerpt"}])
    put(kg, "real-legacy", "Real legacy", alpha, summary="plainlegacy backed")
    kg.close()
    kg = KnowledgeGraph(str(world.db))  # enroll real-legacy as lifecycle-managed legacy evidence
    req = _source(kg, "adopt", 1, alpha)
    store = LifecycleStore(kg)
    store.apply({"action": "observe", **req})
    tok = {k: req[k] for k in ("source_id", "revision", "source_version", "content_hash",
                               "extractor_version", "ontology_version")}
    store.apply({"action": "replace", **tok, "job_id": "adopt-1", "complete": True,
                 "entities": [{"id": "real-legacy", "type": "note", "name": "Real legacy",
                               "properties": {"summary": "plainlegacy backed"}}],
                 "relations": [], "checkpoint": {"cursor": 1}})
    kg.close()
    assert run(world, "alpha-app", "quokka")["status"] == "no_matches"
    results = {r["citation"]["entity_id"]: r for r in run(world, "alpha-app", "plainlegacy")["results"]}
    assert results["forged-legacy"]["provenance"] == []
    assert "legacy:unattributed" in results["real-legacy"]["citation"]["source_ids"]


def test_citation_ids_survive_unrelated_changes_but_track_edits(world):
    before = run(world, "alpha-app", "approved")["results"][0]
    kg = KnowledgeGraph(str(world.db))
    put(kg, "other", "Other scope", world.scopes["beta"], summary="approved elsewhere")
    kg.close()
    after = run(world, "alpha-app", "approved")["results"][0]
    assert before["citation"] == after["citation"]
    assert before["excerpt_sha256"] == after["excerpt_sha256"]
    kg = KnowledgeGraph(str(world.db))
    entity = kg.get_entity(before["citation"]["entity_id"])
    assert entity is not None
    entity.name = "Budget approval decision (revised)"
    kg.update_entity(entity)
    kg.close()
    edited = next(r for r in run(world, "alpha-app", "revised")["results"]
                  if r["citation"]["entity_id"] == before["citation"]["entity_id"])
    assert edited["citation"]["id"] == before["citation"]["id"]
    assert edited["citation"]["entity_version"] > before["citation"]["entity_version"]
    assert edited["excerpt_sha256"] != before["excerpt_sha256"]


# --- unavailable / timeout ----------------------------------------------------------


def test_missing_store_is_unavailable_and_creates_nothing(tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    missing = tmp_path / "no" / "such" / "dir" / "knowledge.db"
    write_config(cfg_dir / "p.json", missing, [grant("a", "scope-1")])
    before = tree_state(tmp_path)
    response = search_evidence(cfg_dir / "p.json", {"app_project": "a", "query": "x"})
    assert (response["status"], response["reason"]) == ("unavailable", "store_missing")
    assert response["freshness"]["cacheable"] is False
    assert tree_state(tmp_path) == before and not (tmp_path / "no").exists()


@pytest.mark.parametrize(
    "kind,reasons",
    [("empty", {"store_uninitialized"}), ("garbage", {"store_unreadable"}),
     ("no_tables", {"store_uninitialized"}), ("old_schema", {"store_schema_unsupported"})],
)
def test_unusable_stores_are_reported_without_modification(tmp_path, kind, reasons):
    db = tmp_path / "s" / "k.db"
    db.parent.mkdir()
    if kind == "empty":
        db.write_bytes(b"")
    elif kind == "garbage":
        db.write_bytes(b"this is not sqlite" * 50)
    else:
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=DELETE")
        if kind == "old_schema":
            conn.execute("CREATE TABLE entities (id TEXT, name TEXT)")
            conn.execute("CREATE TABLE scopes (id TEXT)")
        else:
            conn.execute("CREATE TABLE other (x)")
        conn.commit()
        conn.close()
    cfg = write_config(tmp_path / "p.json", db, [grant("a", "scope-1")])
    before = tree_state(tmp_path)
    response = search_evidence(cfg, {"app_project": "a", "query": "x"})
    assert response["status"] == "unavailable"
    assert response["reason"] in reasons
    assert tree_state(tmp_path) == before


def test_unavailable_scope_is_distinct_from_no_matches(world):
    _cfg = write_config(world.config, world.db, [grant("ghost", "scope-does-not-exist")])
    response = run(world, "ghost")
    assert (response["status"], response["reason"]) == ("unavailable", "scope_unavailable")


def test_existing_scope_without_rows_is_no_matches(world):
    kg = KnowledgeGraph(str(world.db))
    empty = kg.create_scope("project", "Empty").id
    kg.close()
    write_config(world.config, world.db, [grant("empty-app", empty)])
    assert run(world, "empty-app")["status"] == "no_matches"


def test_timeout_is_distinct(tmp_path):
    w = build_world(tmp_path)
    conn = sqlite3.connect(w.db)
    rows = [(f"bulk-{i}", "note", f"Bulk {i}", json.dumps({"s": ("lorem ipsum dolor " * 40)}),
             "t", "t", 1, w.scopes["alpha"], "meeting-test") for i in range(60000)]
    conn.executemany(
        "INSERT INTO entities (id,type,name,properties,created_at,updated_at,version,scope_id,"
        "source_channel) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    response = run(w, "alpha-app", "lorem", timeout_ms=50)
    assert (response["status"], response["reason"]) == ("timeout", "deadline_exceeded")
    assert response["results"] == [] and response["freshness"]["cacheable"] is False


# --- zero writes ------------------------------------------------------------------------


def test_search_writes_nothing_to_a_cleanly_closed_wal_store(world):
    before = tree_state(world.root)
    assert before.get("store/knowledge.db") and "store/knowledge.db-wal" not in before
    for app in ("alpha-app", "beta-app", "unknown-app", "topic-app"):
        run(world, app)
        fresh(world, app)
    assert tree_state(world.root) == before


def test_search_creates_no_sidecars_and_reads_immutable_snapshot(world):
    assert run(world, "alpha-app")["status"] == "ok"
    assert mode_of(world.db) == "immutable"
    assert sorted(p.name for p in world.db.parent.iterdir()) == ["knowledge.db"]


def test_search_with_live_writer_changes_nothing_in_the_store_directory(world):
    live = KnowledgeGraph(str(world.db))  # keeps WAL + shm alive
    try:
        put(live, "live-1", "Live budget", world.scopes["alpha"], summary="uncheckpointed budget")
        assert {"knowledge.db-wal", "knowledge.db-shm"} <= {p.name for p in world.db.parent.iterdir()}
        before = tree_state(world.root)  # includes -wal and -shm bytes and mtimes; before ANY open
        response = run(world, "alpha-app", "uncheckpointed")
        fresh(world, "alpha-app")
        assert ids(response) == {"live-1"}  # committed-but-uncheckpointed data is visible
        assert tree_state(world.root) == before
        assert mode_of(world.db) == "private-copy"
        assert tree_state(world.root) == before
    finally:
        live.close()


def test_idle_rollback_journal_store_is_read_without_writes(tmp_path):
    w = build_world(tmp_path)
    conn = sqlite3.connect(w.db)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    before = tree_state(w.root)
    response = run(w, "alpha-app")
    assert response["status"] == "ok"
    assert mode_of(w.db) == "immutable"
    assert tree_state(w.root) == before


def test_clean_persisted_journal_is_not_mistaken_for_a_hot_journal(tmp_path):
    w = build_world(tmp_path)
    conn = sqlite3.connect(w.db)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA journal_mode=PERSIST")
    conn.execute("UPDATE entities SET version = version WHERE id = 'a-budget'")
    conn.commit()
    conn.close()
    journal = Path(str(w.db) + "-journal")
    assert journal.exists() and journal.stat().st_size > 0
    before = tree_state(w.root)
    response = run(w, "alpha-app")
    assert response["status"] == "ok"
    assert mode_of(w.db) == "private-copy"
    assert tree_state(w.root) == before


HOT_JOURNAL_SCRIPT = """
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1], isolation_level=None)
conn.execute("PRAGMA journal_mode=DELETE")
conn.execute("PRAGMA cache_size=1")
conn.execute("BEGIN")
for i in range(3000):
    conn.execute(
        "INSERT INTO entities (id,type,name,properties,created_at,updated_at,version,scope_id,"
        "source_channel) VALUES (?,?,?,?,?,?,?,?,?)",
        (f"hot-{i}", "note", "hot", "x" * 2000, "t", "t", 1, None, "meeting-test"))
os._exit(0)
"""


def test_hot_rollback_journal_is_recovered_on_a_private_copy_and_store_is_untouched(tmp_path):
    w = build_world(tmp_path)
    conn = sqlite3.connect(w.db)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    subprocess.run([sys.executable, "-c", HOT_JOURNAL_SCRIPT, str(w.db)], check=True)
    journal = Path(str(w.db) + "-journal")
    if not journal.exists() or journal.stat().st_size == 0:
        pytest.skip("could not leave a hot journal on this platform")
    before = tree_state(w.root)
    response = run(w, "alpha-app", limit=20)
    assert response["status"] == "ok"
    assert ids(response) == {"a-budget", "a-risk", "a-decision"}  # last committed state
    assert tree_state(w.root) == before and journal.exists()


def test_wal_content_without_shm_is_read_from_a_private_copy_and_store_is_untouched(tmp_path):
    w = build_world(tmp_path)
    live = KnowledgeGraph(str(w.db))
    put(live, "pending", "Pending budget", w.scopes["alpha"], summary="pending write")
    copy = tmp_path / "copy"
    copy.mkdir()
    shutil.copy(w.db, copy / "knowledge.db")
    shutil.copy(str(w.db) + "-wal", copy / "knowledge.db-wal")
    live.close()
    cfg = write_config(copy / "p.json", copy / "knowledge.db", [grant("a", w.scopes["alpha"])])
    before = tree_state(copy)
    response = search_evidence(cfg, {"app_project": "a", "query": "pending"})
    assert response["status"] == "ok" and ids(response) == {"pending"}
    assert tree_state(copy) == before and not Path(str(copy / "knowledge.db") + "-shm").exists()


def test_private_copy_that_keeps_changing_is_busy_not_inconsistent(world, monkeypatch):
    live = KnowledgeGraph(str(world.db))
    try:
        put(live, "x", "X", world.scopes["alpha"], summary="y")
        counter = iter(range(10_000))
        monkeypatch.setattr(store_mod, "_main_key", lambda path: (next(counter), 0))
        response = run(world, "alpha-app")
        assert (response["status"], response["reason"]) == ("unavailable", "store_busy")
    finally:
        live.close()


def test_oversized_live_store_is_refused_not_written_around(world, monkeypatch):
    live = KnowledgeGraph(str(world.db))
    try:
        monkeypatch.setattr(store_mod, "MAX_COPY_BYTES", 1024)
        response = run(world, "alpha-app")
        assert (response["status"], response["reason"]) == ("unavailable", "store_too_large")
    finally:
        live.close()


def test_private_copy_is_removed_after_each_search(world, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(store_mod.tempfile, "tempdir", str(scratch))
    live = KnowledgeGraph(str(world.db))
    try:
        assert run(world, "alpha-app")["status"] == "ok"
        assert list(scratch.iterdir()) == []
    finally:
        live.close()


def test_immutable_uri_refuses_to_create_a_vanished_store(tmp_path):
    gone = tmp_path / "gone.db"
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(gone.resolve().as_uri() + "?mode=ro&immutable=1", uri=True).execute(
            "SELECT 1 FROM sqlite_master"
        )
    assert not gone.exists()


def test_store_change_during_immutable_read_is_detected(world):
    deadline = store_mod.Deadline(2000)
    snap = store_mod.open_snapshot(world.db, deadline)
    try:
        assert snap.mode == "immutable"
        store_mod.verify_unchanged(snap)
        Path(str(world.db) + "-wal").write_bytes(b"")  # a writer appeared
        with pytest.raises(store_mod.StoreUnavailable) as err:
            store_mod.verify_unchanged(snap)
        assert err.value.reason == "store_changed_during_read"
    finally:
        store_mod.close_snapshot(snap)


def test_symlinked_store_uses_the_target_side_files(world, tmp_path):
    link = tmp_path / "link" / "knowledge.db"
    link.parent.mkdir()
    try:
        link.symlink_to(world.db)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    write_config(world.config, link, [grant("alpha-app", world.scopes["alpha"])])
    live = KnowledgeGraph(str(world.db))
    try:
        put(live, "via-link", "Via link", world.scopes["alpha"], summary="unmistakableword")
        response = run(world, "alpha-app", "unmistakableword")
        assert ids(response) == {"via-link"}
        assert mode_of(world.db) == "private-copy"
    finally:
        live.close()


def test_late_expiry_never_returns_success(world, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(store_mod, "_clock", lambda: now[0])
    original = search_mod._best_excerpt

    def slow_excerpt(*args, **kwargs):
        result = original(*args, **kwargs)
        now[0] += 10.0  # the deadline passes during the last expensive step
        return result

    monkeypatch.setattr(search_mod, "_best_excerpt", slow_excerpt)
    response = run(world, "alpha-app", "approved", limit=1, timeout_ms=50)
    assert (response["status"], response["reason"]) == ("timeout", "deadline_exceeded")
    assert response["results"] == [] and response["freshness"]["cacheable"] is False


# --- freshness ------------------------------------------------------------------------------


def token(world: World, app: str = "alpha-app") -> str:
    response = fresh(world, app)
    assert response["status"] == "ok" and response["freshness"]["cacheable"] is True
    return response["freshness"]["token"]


def test_freshness_token_matches_search_and_is_stable(world):
    t = token(world)
    assert t == token(world) == run(world, "alpha-app")["freshness"]["token"]
    assert token(world, "beta-app") != t
    assert fresh(world, "alpha-app")["results"] == []


def test_edit_changes_token_and_result_is_not_stale(world):
    before_token = token(world)
    kg = KnowledgeGraph(str(world.db))
    entity = kg.get_entity("a-budget")
    entity.properties["summary"] = "The budget was rejected for the alpha launch"
    kg.update_entity(entity)
    kg.close()
    assert token(world) != before_token
    top = next(r for r in run(world, "alpha-app", "rejected")["results"])
    assert top["citation"]["entity_id"] == "a-budget"
    assert run(world, "alpha-app", "approved")["results"][0]["citation"]["entity_id"] == "a-decision"


def test_deletion_changes_token_and_removes_evidence(world):
    before_token = token(world)
    conn = sqlite3.connect(world.db)
    conn.execute("DELETE FROM entities WHERE id = 'a-risk'")
    conn.commit()
    conn.close()
    assert token(world) != before_token
    assert "a-risk" not in ids(run(world, "alpha-app", limit=20))


def _source(kg, source_id, revision, scope, **extra):
    return {"source_id": source_id, "revision": revision, "source_version": f"v{revision}",
            "content_hash": f"h{revision}", "extractor_version": "x1", "ontology_version": "o1",
            "location": f"app://{source_id}", "kind": "meeting", "source_channel": "meeting-test",
            "scope_id": scope, **extra}


def _delete_source(world, source_id, revision):
    kg = KnowledgeGraph(str(world.db))
    try:
        store = LifecycleStore(kg)
        tok = {k: v for k, v in _source(kg, source_id, revision, world.scopes["alpha"]).items()
               if k in {"source_id", "revision", "source_version", "content_hash",
                        "extractor_version", "ontology_version"}}
        store.apply({"action": "observe", **_source(kg, source_id, revision, world.scopes["alpha"])})
        store.apply({"action": "delete", **tok, "job_id": f"del-{source_id}-{revision}",
                     "checkpoint": {"cursor": revision}, "deletion": {"kind": "explicit"}})
    finally:
        kg.close()


def test_lifecycle_source_deletion_changes_token_and_removes_evidence(world):
    before = fresh(world, "alpha-app")["freshness"]
    _delete_source(world, "alpha-meeting", 2)
    after = fresh(world, "alpha-app")["freshness"]
    assert after["token"] != before["token"]
    assert "a-decision" not in ids(run(world, "alpha-app", limit=20))


def test_deleting_a_source_without_evidence_still_changes_token(world):
    kg = KnowledgeGraph(str(world.db))
    store = LifecycleStore(kg)
    req = _source(kg, "empty-meeting", 1, world.scopes["alpha"])
    store.apply({"action": "observe", **req})
    tok = {k: req[k] for k in ("source_id", "revision", "source_version", "content_hash",
                               "extractor_version", "ontology_version")}
    store.apply({"action": "replace", **tok, "job_id": "empty-1", "complete": True,
                 "entities": [], "relations": [], "checkpoint": {"cursor": 1}})
    kg.close()
    before = token(world)
    _delete_source(world, "empty-meeting", 2)
    assert token(world) != before


def test_freshness_does_not_expose_store_wide_counters(world):
    data = fresh(world, "alpha-app")["freshness"]["data"]
    assert set(data) == {"token", "basis"}


def test_other_scope_changes_do_not_change_token(world):
    t = token(world)
    kg = KnowledgeGraph(str(world.db))
    put(kg, "global-new", "Global new", None, summary="budget")
    put(kg, "beta-new", "Beta new", world.scopes["beta"], summary="budget")
    put(kg, "child-new", "Child new", world.scopes["topic"], summary="budget")
    kg.close()
    assert token(world) == t  # the store-wide lifecycle generation moved; the scope did not


def test_grant_changes_change_token_and_revocation_bypasses_cache(world):
    s = world.scopes
    t = token(world)
    _config(world, [grant("alpha-app", s["alpha"], "rotated")])
    assert token(world) != t  # same scope, different grant identity
    rotated = token(world)
    _config(world, [grant("alpha-app", s["beta"], "rebound")])
    assert token(world) != rotated  # rebound scope
    _config(world, [grant("alpha-app", s["beta"], "rebound", "revoked")])
    revoked = fresh(world, "alpha-app")
    assert revoked["status"] == "unauthorized"
    assert revoked["freshness"]["cacheable"] is False and revoked["freshness"]["token"] is None


def test_error_responses_always_bypass_cache(world):
    for response in (run(world, "nope"), run(world, "alpha-app", query=""),
                     fresh(world, "nope")):
        assert response["status"] != "ok"
        assert response["freshness"]["cacheable"] is False
        assert response["freshness"]["bypass_reason"]


# --- CLI ----------------------------------------------------------------------------------------


def cli(capsys, *argv: str):
    with pytest.raises(SystemExit) as exc:
        cli_main(list(argv))
    out = capsys.readouterr().out
    return exc.value.code, json.loads(out)


def cli_ok(capsys, *argv: str) -> Dict[str, Any]:
    try:
        cli_main(list(argv))
    except SystemExit as exc:  # pragma: no cover - only on failure
        raise AssertionError(f"exit {exc.code}") from exc
    return json.loads(capsys.readouterr().out)


def test_cli_search_freshness_and_exit_codes(world, capsys):
    base = ["evidence", "search", "--provider-config", str(world.config)]
    response = cli_ok(capsys, *base, "--app-project", "alpha-app", "--query", "budget",
                      "--limit", "2")
    assert response["status"] == "ok" and len(response["results"]) == 2
    assert cli_ok(capsys, "evidence", "freshness", "--provider-config", str(world.config),
                  "--app-project", "alpha-app")["freshness"]["cacheable"] is True
    code, body = cli(capsys, *base, "--app-project", "nobody", "--query", "budget")
    assert code == 3 and body["status"] == "unauthorized"
    code, body = cli(capsys, *base, "--app-project", "alpha-app", "--query", "")
    assert code == 2 and body["status"] == "invalid_request"
    ghost = write_config(world.root / "ghost.json", world.root / "none.db", [grant("g", "s")])
    code, body = cli(capsys, "evidence", "search", "--provider-config", str(ghost),
                     "--app-project", "g", "--query", "x")
    assert code == 4 and body["reason"] == "store_missing"


@pytest.mark.parametrize("flag", ["--scope", "--scope-id", "--store", "--caller", "--db-path"])
def test_cli_has_no_scope_store_or_caller_options(world, flag):
    with pytest.raises(SystemExit) as exc:
        cli_main(["evidence", "search", "--provider-config", str(world.config),
                  "--app-project", "alpha-app", "--query", "x", flag, "y"])
    assert exc.value.code == 2


def test_cli_provider_config_from_environment(world, capsys, monkeypatch):
    monkeypatch.setenv("MNEMOSYNE_EVIDENCE_PROVIDER_CONFIG", str(world.config))
    out = cli_ok(capsys, "evidence", "search", "--app-project", "beta-app", "--query", "budget")
    assert out["status"] == "ok"


def test_untrusted_optional_args_are_not_required_in_requests(world):
    # defaults apply when optional fields are omitted
    response = search_evidence(world.config, {"app_project": "alpha-app", "query": "budget"})
    assert response["bounds"]["limit"] == 5
    assert response["bounds"]["max_excerpt_chars"] == 400



def test_legacy_backing_membership_is_part_of_the_freshness_token(world):
    alpha = world.scopes["alpha"]
    kg = KnowledgeGraph(str(world.db))
    put(kg, "legacy-x", "Legacy x", alpha, summary="legacywording")
    kg.close()
    before = token(world)
    kg = KnowledgeGraph(str(world.db))
    req = _source(kg, "adopt-x", 1, alpha)
    store = LifecycleStore(kg)
    store.apply({"action": "observe", **req})
    tok = {k: req[k] for k in ("source_id", "revision", "source_version", "content_hash",
                               "extractor_version", "ontology_version")}
    store.apply({"action": "replace", **tok, "job_id": "adopt-x-1", "complete": True,
                 "entities": [{"id": "legacy-x", "type": "note", "name": "Legacy x",
                               "properties": {"summary": "legacywording"}}],
                 "relations": [], "checkpoint": {"cursor": 1}})
    kg.close()
    conn = sqlite3.connect(world.db)
    backed = conn.execute("SELECT COUNT(*) FROM lifecycle_legacy WHERE target_id='legacy-x'").fetchone()
    conn.close()
    assert backed[0] == 1
    assert token(world) != before
    # Membership alone (nothing else in the scope changes) moves the token too.
    mid = token(world)
    conn = sqlite3.connect(world.db)
    conn.execute("DELETE FROM lifecycle_legacy WHERE target_id='legacy-x'")
    conn.commit()
    conn.close()
    assert token(world) != mid


def test_response_byte_budget_cuts_results_and_reports_truncation(tmp_path, monkeypatch):
    w = build_world(tmp_path)
    kg = KnowledgeGraph(str(w.db))
    for i in range(20):
        put(kg, f"big-{i}", f"Big {i}", w.scopes["alpha"], summary="budget " + "x" * 900)
    kg.close()
    monkeypatch.setattr(search_mod, "_RESULT_BUDGET_BYTES", 3000)
    response = run(w, "alpha-app", limit=20, max_excerpt_chars=1200)
    assert response["bounds"]["truncated"] is True
    assert 0 < len(response["results"]) < 20
    assert sum(len(json.dumps(r, ensure_ascii=False).encode()) for r in response["results"]) <= 3000
    assert response["bounds"]["total_matches"] >= 20


def test_private_copy_is_removed_even_when_opening_fails_midway(world, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch2"
    scratch.mkdir()
    monkeypatch.setattr(store_mod.tempfile, "tempdir", str(scratch))

    def boom(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(store_mod, "_install_deadline", boom)
    live = KnowledgeGraph(str(world.db))
    try:
        response = run(world, "alpha-app")
        assert (response["status"], response["reason"]) == ("unavailable", "store_unreadable")
        assert list(scratch.iterdir()) == []
    finally:
        live.close()


# --- fail-closed caching for unprovable snapshots -------------------------------------------


def assert_bypass(response: Dict[str, Any], reason: str) -> None:
    fresh_block = response["freshness"]
    assert response["status"] in {"ok", "no_matches"}  # evidence is still returned
    assert fresh_block["cacheable"] is False and fresh_block["token"] is None
    assert fresh_block["authorization"] is None and fresh_block["data"] is None
    assert fresh_block["bypass_reason"] == reason


def test_unattested_writer_mode_is_never_cacheable(world):
    write_config(world.config, world.db, [grant("alpha-app", world.scopes["alpha"])],
                 attest_wal=False)
    assert "a-budget" in ids(run(world, "alpha-app"))
    assert_bypass(run(world, "alpha-app"), "writer_mode_unattested")
    assert_bypass(fresh(world, "alpha-app"), "writer_mode_unattested")
    write_config(world.config, world.db, [grant("alpha-app", world.scopes["alpha"])])
    assert token(world)  # the operator attestation is what makes it provable


def test_unverifiable_oversized_store_bypasses_caching(world, monkeypatch):
    monkeypatch.setattr(store_mod, "MAX_COPY_BYTES", 1024)
    response = run(world, "alpha-app")
    assert "a-budget" in ids(response)
    assert_bypass(response, "store_too_large_to_verify")


def test_rewrite_that_preserves_size_and_mtime_is_caught_by_content_digest(world, monkeypatch):
    original = search_mod._scoped_read

    def tamper(*args, **kwargs):
        result = original(*args, **kwargs)
        stat = world.db.stat()
        with open(world.db, "r+b") as handle:  # header application_id: same size, still valid
            handle.seek(68)
            handle.write(b"\x01")
        os.utime(world.db, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        return result

    monkeypatch.setattr(search_mod, "_scoped_read", tamper)
    response = run(world, "alpha-app")
    assert (response["status"], response["reason"]) == ("unavailable", "store_changed_during_read")
    assert response["freshness"]["cacheable"] is False


def test_recent_writes_and_other_scope_edits_do_not_depend_on_wall_clock(world):
    t = token(world)
    kg = KnowledgeGraph(str(world.db))
    put(kg, "beta-new", "Beta new", world.scopes["beta"], summary="budget")
    kg.close()  # a write that just happened, in another scope
    assert token(world) == t  # still authoritative and unchanged for alpha
    kg = KnowledgeGraph(str(world.db))
    put(kg, "alpha-new", "Alpha new", world.scopes["alpha"], summary="budget")
    kg.close()
    assert token(world) != t  # an immediate in-scope edit is authoritatively detected


def test_live_writer_results_are_returned_but_never_cacheable(world):
    live = KnowledgeGraph(str(world.db))
    try:
        put(live, "live-1", "Live budget", world.scopes["alpha"], summary="uncheckpointed budget")
        search = run(world, "alpha-app", "uncheckpointed")
        assert ids(search) == {"live-1"}
        assert_bypass(search, "live_store_snapshot_unpublished")
        assert_bypass(fresh(world, "alpha-app"), "live_store_snapshot_unpublished")
        assert_bypass(run(world, "alpha-app", "zzzqqq"),
                      "live_store_snapshot_unpublished")  # no_matches bypasses too
    finally:
        live.close()
    assert token(world)  # writer gone, store quiet: authoritative again


def test_journaled_and_crashed_wal_stores_are_never_cacheable(tmp_path):
    w = build_world(tmp_path / "persist")
    conn = sqlite3.connect(w.db)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA journal_mode=PERSIST")
    conn.execute("UPDATE entities SET version = version WHERE id = 'a-budget'")
    conn.commit()
    conn.close()
    assert_bypass(run(w, "alpha-app"), "live_store_snapshot_unpublished")

    w2 = build_world(tmp_path / "crashed")
    live = KnowledgeGraph(str(w2.db))
    put(live, "pending", "Pending budget", w2.scopes["alpha"], summary="pending write")
    copy = tmp_path / "copy"
    copy.mkdir()
    shutil.copy(w2.db, copy / "knowledge.db")
    shutil.copy(str(w2.db) + "-wal", copy / "knowledge.db-wal")
    live.close()
    cfg = write_config(copy / "p.json", copy / "knowledge.db", [grant("a", w2.scopes["alpha"])])
    response = search_evidence(cfg, {"app_project": "a", "query": "pending"})
    assert ids(response) == {"pending"}
    assert_bypass(response, "live_store_snapshot_unpublished")


def test_authoritative_paths_still_invalidate_on_edit_delete_and_revocation(world):
    s = world.scopes
    t0 = token(world)
    kg = KnowledgeGraph(str(world.db))
    entity = kg.get_entity("a-budget")
    entity.properties["summary"] = "The budget was rejected"
    kg.update_entity(entity)
    kg.close()
    t1 = token(world)
    assert t1 != t0
    conn = sqlite3.connect(world.db)
    conn.execute("DELETE FROM entities WHERE id = 'a-risk'")
    conn.commit()
    conn.close()
    t2 = token(world)
    assert t2 not in {t0, t1}
    _config(world, [grant("alpha-app", s["alpha"], "r", "revoked")])
    revoked = fresh(world, "alpha-app")
    assert revoked["status"] == "unauthorized" and revoked["freshness"]["token"] is None

"""Tests for persistent Markdown LLM Wiki maintenance."""

from __future__ import annotations

import json
from pathlib import Path

from mnemosyne.ingest.llm_extractor import IngestEntity, IngestRelation, ParsedIngestResult
from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer


def _parsed() -> ParsedIngestResult:
    return ParsedIngestResult(
        source_file="meeting.md",
        domain="daily",
        entities=[
            IngestEntity(
                id="alice",
                label="Alice",
                type="person",
                source_file="meeting.md",
                properties={"role": "researcher"},
            ),
            IngestEntity(
                id="mnemosyne",
                label="Mnemosyne",
                type="project",
                source_file="meeting.md",
            ),
        ],
        relations=[
            IngestRelation(source="alice", target="mnemosyne", relation="works_on"),
        ],
    )


def test_update_from_ingest_creates_index_log_source_and_entity_pages(tmp_path):
    source = tmp_path / "meeting.md"
    source.write_text("Alice works on Mnemosyne.", encoding="utf-8")
    wiki_root = tmp_path / "wiki"

    update = LLMWikiMaintainer(wiki_root).update_from_ingest(
        _parsed(),
        source=str(source),
        domain="daily",
        scope_id="demo-session",
        source_channel="cli",
        raw_path=source,
    )

    assert wiki_root / "index.md" in update.paths
    assert wiki_root / "log.md" in update.paths
    assert (wiki_root / "sources" / "daily" / "meeting.md").exists()
    alice_page = wiki_root / "entities" / "person" / "alice.md"
    assert alice_page.exists()

    index = (wiki_root / "index.md").read_text(encoding="utf-8")
    assert "[[entities/person/alice|Alice]]" in index
    assert "[[sources/daily/meeting|meeting.md]]" in index

    alice = alice_page.read_text(encoding="utf-8")
    assert "demo-session" in alice
    assert "works_on" in alice
    assert "[[sources/daily/meeting|meeting.md]]" in alice

    log = (wiki_root / "log.md").read_text(encoding="utf-8")
    assert "ingest | meeting.md" in log
    assert "**Entities**: 2" in log


def test_entity_page_preserves_manual_notes_and_accumulates_sources(tmp_path):
    wiki_root = tmp_path / "wiki"
    maintainer = LLMWikiMaintainer(wiki_root)

    first = tmp_path / "first.md"
    first.write_text("Alice starts.", encoding="utf-8")
    maintainer.update_from_ingest(
        _parsed(),
        source=str(first),
        domain="daily",
        raw_path=first,
    )

    alice_page = wiki_root / "entities" / "person" / "alice.md"
    with alice_page.open("a", encoding="utf-8") as fh:
        fh.write("Manual observation stays here.\n")

    second = tmp_path / "second.md"
    second.write_text("Alice continues.", encoding="utf-8")
    maintainer.update_from_ingest(
        _parsed(),
        source=str(second),
        domain="daily",
        raw_path=second,
    )

    alice = alice_page.read_text(encoding="utf-8")
    assert "Manual observation stays here." in alice
    assert "[[sources/daily/first|first.md]]" in alice
    assert "[[sources/daily/second|second.md]]" in alice


def test_source_excerpts_are_omitted_by_default_and_opt_in_redacts(tmp_path):
    source = tmp_path / "secret.md"
    source.write_text("api_key = sk-1234567890abcdef\nAlice works.", encoding="utf-8")
    wiki_root = tmp_path / "wiki"

    LLMWikiMaintainer(wiki_root).update_from_ingest(
        _parsed(), source=str(source), domain="daily", raw_path=source
    )
    source_page = wiki_root / "sources" / "daily" / "secret.md"
    text = source_page.read_text(encoding="utf-8")
    assert "sk-1234567890abcdef" not in text
    assert "Omitted by default" in text
    assert "page_type: \"source\"" in text
    assert "content_hash:" in text

    LLMWikiMaintainer(wiki_root, include_excerpts=True).update_from_ingest(
        _parsed(), source=str(source), domain="daily", raw_path=source
    )
    text = source_page.read_text(encoding="utf-8")
    assert "[REDACTED]" in text
    assert "sk-1234567890abcdef" not in text


def test_entity_page_renders_redacted_potential_contradictions(tmp_path):
    wiki_root = tmp_path / "wiki"
    source = tmp_path / "meeting.md"
    source.write_text("Alice role changed.", encoding="utf-8")
    parsed = ParsedIngestResult(
        source_file=str(source),
        domain="daily",
        entities=[
            IngestEntity(
                id="alice",
                label="Alice",
                type="person",
                source_file=str(source),
                properties={
                    "role": "engineer",
                    "conflicts": {
                        "role": [
                            {
                                "existing": "engineer api_key = sk-1234567890abcdef",
                                "incoming": "architect token = sk-abcdef1234567890",
                                "source_file": str(source),
                                "source_id": "source-1",
                                "detected_at": "2026-05-03T00:00:00+00:00",
                                "resolution": "unresolved",
                            }
                        ]
                    },
                },
            )
        ],
        relations=[],
    )

    LLMWikiMaintainer(wiki_root).update_from_ingest(parsed, source=str(source), domain="daily", raw_path=source)

    text = (wiki_root / "entities" / "person" / "alice.md").read_text(encoding="utf-8")
    assert "## Potential contradictions" in text
    assert "Needs review" in text
    assert "not an LLM semantic truth judgment" in text
    assert "source-1" in text
    assert "resolution: `unresolved`" in text
    assert "sk-1234567890abcdef" not in text
    assert "sk-abcdef1234567890" not in text
    assert "[REDACTED]" in text
    assert "**conflicts**" not in text


def test_conflict_normalization_handles_legacy_current_and_resolved_records():
    entity = IngestEntity(
        id="alice",
        label="Alice",
        type="person",
        source_file="graph://demo",
        properties={
            "role": "engineer",
            "conflicts": {
                "role": [
                    {
                        "existing": "engineer",
                        "incoming": "architect",
                        "source_file": "meeting.md",
                        "seen_at": "2026-05-03T00:00:00+00:00",
                    }
                ],
                "status": [
                    {
                        "existing": "active",
                        "incoming": "inactive",
                        "detected_at": "2026-05-03T01:00:00+00:00",
                        "resolution": "accepted_existing",
                    }
                ],
                "legacy_value": ["incoming-only"],
            },
        },
    )

    conflicts = LLMWikiMaintainer._normalize_conflicts(entity)
    by_property = {item.property_name: item for item in conflicts}

    assert by_property["role"].resolution == "unresolved"
    assert by_property["role"].source_file == "meeting.md"
    assert by_property["role"].source_id == LLMWikiMaintainer._source_id("meeting.md")
    assert by_property["status"].resolution == "accepted_existing"
    assert by_property["status"].source_file == "unknown"
    assert by_property["status"].source_id == "unknown"
    assert by_property["legacy_value"].incoming == "incoming-only"


def test_status_and_lint_expose_unresolved_contradictions(tmp_path, capsys):
    from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph
    from mnemosyne.wiki.cli import main

    db_path = tmp_path / "kg.db"
    kg = KnowledgeGraph(str(db_path))
    kg.add_entity(Entity(
        id="alice",
        type="person",
        name="Alice",
        properties={
            "source_file": "graph://demo",
            "source_files": ["graph://demo"],
            "conflicts": {
                "role": [
                    {
                        "existing": "engineer",
                        "incoming": "architect",
                        "source_file": "meeting.md",
                        "detected_at": "2026-05-03T00:00:00+00:00",
                        "resolution": "unresolved",
                    },
                    {
                        "existing": "engineer",
                        "incoming": "manager",
                        "source_file": "review.md",
                        "detected_at": "2026-05-03T01:00:00+00:00",
                        "resolution": "accepted_existing",
                    },
                ]
            },
        },
        created_at="",
        updated_at="",
    ))
    kg.close()

    wiki_root = tmp_path / "wiki"
    maintainer = LLMWikiMaintainer(wiki_root)
    maintainer.rebuild_from_graph(db_path)

    status = maintainer.status(db_path=db_path)
    assert status["contradictions"]["total"] == 2
    assert status["contradictions"]["unresolved"] == 1
    assert status["contradictions"]["resolved"] == 1
    assert status["contradictions"]["by_entity"]["alice"]["unresolved"] == 1

    report = maintainer.lint(db_path=db_path)
    assert report.ok
    unresolved = [issue for issue in report.warnings if issue.code == "unresolved-contradiction"]
    assert len(unresolved) == 1
    assert "conflict metadata only" in unresolved[0].message

    assert main(["status", "--wiki-root", str(wiki_root), "--db-path", str(db_path), "--format", "json"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["contradictions"]["unresolved"] == 1

    assert main(["lint", "--wiki-root", str(wiki_root), "--db-path", str(db_path), "--format", "json"]) == 0
    lint_payload = json.loads(capsys.readouterr().out)
    assert lint_payload["warning_count"] == 1
    assert lint_payload["warnings"][0]["code"] == "unresolved-contradiction"

    assert main(["lint", "--wiki-root", str(wiki_root), "--db-path", str(db_path), "--strict"]) == 1
    capsys.readouterr()


def test_contradiction_resolution_updates_only_review_metadata_and_history(tmp_path):
    from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph

    db_path = tmp_path / "kg.db"
    kg = KnowledgeGraph(str(db_path))
    kg.add_entity(Entity(
        id="alice",
        type="person",
        name="Alice",
        properties={
            "source_file": "graph://demo",
            "source_files": ["graph://demo"],
            "role": "engineer",
            "conflicts": {
                "role": [
                    {
                        "existing": "engineer",
                        "incoming": "architect",
                        "source_file": "meeting.md",
                        "source_id": "source-1",
                        "detected_at": "2026-05-03T00:00:00+00:00",
                        "resolution": "unresolved",
                    }
                ]
            },
        },
        created_at="",
        updated_at="",
    ))
    kg.close()

    maintainer = LLMWikiMaintainer(tmp_path / "wiki")
    conflict = maintainer.list_contradictions(db_path)[0]
    conflict_id = conflict["conflict_id"]
    assert conflict_id.startswith("c_")

    dry_run = maintainer.resolve_contradiction(
        db_path,
        conflict_id=conflict_id,
        resolution="accepted_existing",
        note="Reviewed in standup",
        reviewer="qa",
        dry_run=True,
    )
    assert dry_run["updated"] is False

    kg = KnowledgeGraph(str(db_path))
    try:
        entity = kg.get_entity("alice")
        assert entity is not None
        assert entity.version == 1
        assert entity.properties["conflicts"]["role"][0]["resolution"] == "unresolved"
        assert len(kg.get_entity_history("alice")) == 1
    finally:
        kg.close()

    result = maintainer.resolve_contradiction(
        db_path,
        conflict_id=conflict_id,
        resolution="accepted_existing",
        note="Reviewed in standup",
        reviewer="qa",
    )
    assert result["updated"] is True
    assert result["rebuild_required"] is True
    assert result["before"]["resolution"] == "unresolved"
    assert result["after"]["resolution"] == "accepted_existing"
    assert result["after"]["conflict_id"] == conflict_id

    kg = KnowledgeGraph(str(db_path))
    try:
        entity = kg.get_entity("alice")
        assert entity is not None
        entry = entity.properties["conflicts"]["role"][0]
        assert entity.version == 2
        assert entry["existing"] == "engineer"
        assert entry["incoming"] == "architect"
        assert entry["source_file"] == "meeting.md"
        assert entry["source_id"] == "source-1"
        assert entry["detected_at"] == "2026-05-03T00:00:00+00:00"
        assert entry["resolution"] == "accepted_existing"
        assert entry["review_note"] == "Reviewed in standup"
        assert entry["reviewer"] == "qa"
        assert entry["reviewed_at"]
        assert len(kg.get_entity_history("alice")) == 2
    finally:
        kg.close()

    assert maintainer.list_contradictions(db_path) == []
    all_items = maintainer.list_contradictions(db_path, include_resolved=True)
    assert all_items[0]["conflict_id"] == conflict_id
    assert all_items[0]["resolution"] == "accepted_existing"
    assert maintainer.status(db_path=db_path)["contradictions"]["resolution_counts"]["accepted_existing"] == 1
    assert not any(issue.code == "unresolved-contradiction" for issue in maintainer.lint(db_path=db_path).warnings)


def test_wiki_cli_lists_and_resolves_contradictions_json(tmp_path, capsys):
    from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph
    from mnemosyne.wiki.cli import main

    db_path = tmp_path / "kg.db"
    kg = KnowledgeGraph(str(db_path))
    kg.add_entity(Entity(
        id="alice",
        type="person",
        name="Alice",
        properties={
            "source_file": "graph://demo",
            "source_files": ["graph://demo"],
            "conflicts": {
                "role": [
                    {
                        "existing": "engineer",
                        "incoming": "architect",
                        "source_file": "meeting.md",
                        "detected_at": "2026-05-03T00:00:00+00:00",
                    }
                ]
            },
        },
        created_at="",
        updated_at="",
    ))
    kg.close()

    wiki_root = tmp_path / "wiki"
    assert main(["contradictions", "--wiki-root", str(wiki_root), "--db-path", str(db_path), "--format", "json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["count"] == 1
    conflict_id = listed["items"][0]["conflict_id"]

    assert main([
        "resolve",
        conflict_id,
        "--wiki-root",
        str(wiki_root),
        "--db-path",
        str(db_path),
        "--resolution",
        "ambiguous",
        "--note",
        "Need source owner review",
        "--format",
        "json",
        "--dry-run",
    ]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["updated"] is False

    assert main([
        "resolve",
        conflict_id,
        "--wiki-root",
        str(wiki_root),
        "--db-path",
        str(db_path),
        "--resolution",
        "ambiguous",
        "--note",
        "Need source owner review",
        "--format",
        "json",
    ]) == 0
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["updated"] is True
    assert resolved["after"]["resolution"] == "ambiguous"

    assert main(["contradictions", "--wiki-root", str(wiki_root), "--db-path", str(db_path), "--format", "json"]) == 0
    unresolved = json.loads(capsys.readouterr().out)
    assert unresolved["count"] == 0

    assert main(["contradictions", "--wiki-root", str(wiki_root), "--db-path", str(db_path), "--format", "json", "--all"]) == 0
    all_items = json.loads(capsys.readouterr().out)
    assert all_items["count"] == 1
    assert all_items["items"][0]["resolution"] == "ambiguous"


def test_stale_plan_reports_orphan_pages_missing_sources_and_lint_status(tmp_path):
    from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph

    raw = tmp_path / "meeting.md"
    raw.write_text("Alice works on Mnemosyne.", encoding="utf-8")
    db_path = tmp_path / "kg.db"
    kg = KnowledgeGraph(str(db_path))
    kg.add_entity(Entity(
        id="alice",
        type="person",
        name="Alice",
        properties={"source_file": str(raw), "source_files": [str(raw)]},
        created_at="",
        updated_at="",
    ))
    kg.close()

    wiki_root = tmp_path / "wiki"
    maintainer = LLMWikiMaintainer(wiki_root)
    maintainer.rebuild_from_graph(db_path)
    alice_page = wiki_root / "entities" / "person" / "alice.md"
    with alice_page.open("a", encoding="utf-8") as fh:
        fh.write("Manual note survives stale planning.\n")

    raw.unlink()
    kg = KnowledgeGraph(str(db_path))
    try:
        kg.conn.execute("DELETE FROM entities WHERE id = ?", ("alice",))
        kg.conn.commit()
    finally:
        kg.close()

    plan = maintainer.stale_plan(db_path)
    kinds = {item["kind"] for item in plan["candidates"]}
    assert plan["dry_run"] is True
    assert plan["deletes_performed"] == 0
    assert "stale-wiki-entity-page" in kinds
    assert "stale-wiki-source-page" in kinds
    assert "missing-raw-source" in kinds
    entity_candidate = next(item for item in plan["candidates"] if item["kind"] == "stale-wiki-entity-page")
    assert entity_candidate["risk"] == "high"
    assert entity_candidate["path"] == "entities/person/alice.md"
    assert "Manual note survives stale planning" in entity_candidate["manual_note_preview"]

    status = maintainer.status(db_path=db_path)
    assert status["stale"]["total"] >= 3
    assert status["stale"]["by_kind"]["stale-wiki-entity-page"] == 1

    report = maintainer.lint(db_path=db_path)
    stale_warnings = [issue for issue in report.warnings if issue.code == "stale-candidate"]
    assert stale_warnings
    assert report.ok


def test_wiki_prune_cli_writes_tombstones_without_deleting_pages(tmp_path, capsys):
    from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph
    from mnemosyne.wiki.cli import main

    raw = tmp_path / "meeting.md"
    raw.write_text("Alice works on Mnemosyne.", encoding="utf-8")
    db_path = tmp_path / "kg.db"
    kg = KnowledgeGraph(str(db_path))
    kg.add_entity(Entity(
        id="alice",
        type="person",
        name="Alice",
        properties={"source_file": str(raw), "source_files": [str(raw)]},
        created_at="",
        updated_at="",
    ))
    kg.close()

    wiki_root = tmp_path / "wiki"
    maintainer = LLMWikiMaintainer(wiki_root)
    maintainer.rebuild_from_graph(db_path)
    alice_page = wiki_root / "entities" / "person" / "alice.md"
    with alice_page.open("a", encoding="utf-8") as fh:
        fh.write("Manual recovery note.\n")

    kg = KnowledgeGraph(str(db_path))
    try:
        kg.conn.execute("DELETE FROM entities WHERE id = ?", ("alice",))
        kg.conn.commit()
    finally:
        kg.close()

    assert main(["prune", "--wiki-root", str(wiki_root), "--db-path", str(db_path), "--format", "json"]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["dry_run"] is True
    assert dry_run["tombstones_written"] == 0
    assert dry_run["count"] >= 1

    assert main([
        "prune",
        "--wiki-root",
        str(wiki_root),
        "--db-path",
        str(db_path),
        "--format",
        "json",
        "--apply-tombstones",
    ]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["dry_run"] is False
    assert applied["deletes_performed"] == 0
    assert applied["tombstones_written"] >= 1
    assert alice_page.exists()
    tombstone_texts = [
        Path(path).read_text(encoding="utf-8")
        for path in applied["tombstone_paths"]
        if "stale-wiki-entity-page" in Path(path).read_text(encoding="utf-8")
    ]
    assert tombstone_texts
    assert "Manual recovery note." in tombstone_texts[0]
    assert "Deletes performed**: `0`" in tombstone_texts[0]


def test_semantic_contradiction_discovery_is_opt_in_local_and_separate(tmp_path):
    from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph

    db_path = tmp_path / "kg.db"
    kg = KnowledgeGraph(str(db_path))
    kg.add_entity(Entity(
        id="project-alpha-a",
        type="project",
        name="Project Alpha",
        properties={
            "source_file": "graph://brief-a",
            "status": "active",
            "token": "secret-token-value",
        },
        created_at="",
        updated_at="",
    ))
    kg.add_entity(Entity(
        id="project-alpha-b",
        type="project",
        name="Project Alpha",
        properties={
            "source_file": "graph://brief-b",
            "state": "inactive",
        },
        created_at="",
        updated_at="",
    ))
    kg.add_entity(Entity(
        id="project-beta-a",
        type="project",
        name="Project Beta",
        properties={"source_file": "graph://brief-c", "status": "active"},
        created_at="",
        updated_at="",
    ))
    kg.add_entity(Entity(
        id="project-beta-b",
        type="project",
        name="Project Beta",
        properties={"source_file": "graph://brief-d", "state": "active"},
        created_at="",
        updated_at="",
    ))
    kg.close()

    maintainer = LLMWikiMaintainer(tmp_path / "wiki")

    status_before = maintainer.status(db_path=db_path)
    assert status_before["semantic_contradictions"]["total"] == 0

    dry_run = maintainer.discover_semantic_contradictions(db_path)
    assert dry_run["schema"] == "mnemosyne.semantic_contradiction_candidates.v1"
    assert dry_run["processing_mode"] == "local-offline"
    assert dry_run["remote_model"] is False
    assert dry_run["persisted"] is False
    assert dry_run["count"] == 1
    candidate = dry_run["candidates"][0]
    assert candidate["claim_type"] == "status"
    assert candidate["confidence"] < 1
    assert "not truth judgments" in dry_run["candidate_wording"]
    assert {item["entity_id"] for item in candidate["evidence"]} == {
        "project-alpha-a",
        "project-alpha-b",
    }
    assert all(item["excerpt_kind"] == "property-value-redacted" for item in candidate["evidence"])
    assert "secret-token-value" not in json.dumps(dry_run)

    assert maintainer.status(db_path=db_path)["semantic_contradictions"]["total"] == 0

    written = maintainer.discover_semantic_contradictions(db_path, write=True)
    assert written["persisted"] is True
    assert len(written["paths"]) == 2
    review_json = tmp_path / "wiki" / "review" / "semantic-contradictions.json"
    review_md = tmp_path / "wiki" / "review" / "semantic-contradictions.md"
    assert review_json.exists()
    assert review_md.exists()
    assert "Deterministic graph conflict metadata remains separate" in review_md.read_text(encoding="utf-8")

    status_after = maintainer.status(db_path=db_path)
    assert status_after["semantic_contradictions"]["total"] == 1
    assert status_after["semantic_contradictions"]["open"] == 1
    report = maintainer.lint(db_path=db_path)
    semantic_warnings = [
        issue for issue in report.warnings if issue.code == "semantic-contradiction-candidate"
    ]
    assert len(semantic_warnings) == 1
    assert report.ok


def test_wiki_semantic_contradictions_cli_writes_review_candidates(tmp_path, capsys):
    from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph
    from mnemosyne.wiki.cli import main

    db_path = tmp_path / "kg.db"
    kg = KnowledgeGraph(str(db_path))
    kg.add_entity(Entity(
        id="alice-a",
        type="person",
        name="Alice",
        properties={"source_file": "graph://hr", "role": "owner"},
        created_at="",
        updated_at="",
    ))
    kg.add_entity(Entity(
        id="alice-b",
        type="person",
        name="Alice",
        properties={"source_file": "graph://ops", "responsible": "observer"},
        created_at="",
        updated_at="",
    ))
    kg.close()

    wiki_root = tmp_path / "wiki"
    assert main([
        "semantic-contradictions",
        "--wiki-root",
        str(wiki_root),
        "--db-path",
        str(db_path),
        "--format",
        "json",
        "--write",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["processing_mode"] == "local-offline"
    assert payload["remote_model"] is False
    assert payload["count"] == 1
    assert payload["candidates"][0]["claim_type"] == "responsibility"
    assert (wiki_root / "review" / "semantic-contradictions.json").exists()


def test_lint_detects_broken_links_and_status_counts_pages(tmp_path):
    wiki_root = tmp_path / "wiki"
    source = tmp_path / "meeting.md"
    source.write_text("Alice works on Mnemosyne.", encoding="utf-8")
    maintainer = LLMWikiMaintainer(wiki_root)
    maintainer.update_from_ingest(_parsed(), source=str(source), domain="daily", raw_path=source)

    bad = wiki_root / "bad.md"
    bad.write_text("# Bad\n\n[[missing/page]]\n", encoding="utf-8")

    report = maintainer.lint()
    assert not report.ok
    assert any(issue.code == "broken-link" for issue in report.errors)

    status = maintainer.status()
    assert status["entity_pages"] == 2
    assert status["source_pages"] == 1
    assert status["broken_links"] == 1


def test_rebuild_from_graph_preserves_manual_notes(tmp_path):
    from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph, Relation

    db_path = tmp_path / "kg.db"
    kg = KnowledgeGraph(str(db_path))
    kg.add_entity(Entity(
        id="alice",
        type="person",
        name="Alice",
        properties={"source_file": "graph://demo", "source_files": ["graph://demo"]},
        created_at="",
        updated_at="",
    ))
    kg.add_entity(Entity(
        id="mnemosyne",
        type="project",
        name="Mnemosyne",
        properties={"source_file": "graph://demo", "source_files": ["graph://demo"]},
        created_at="",
        updated_at="",
    ))
    kg.add_relation(Relation(
        id="alice__works_on__mnemosyne",
        source_id="alice",
        target_id="mnemosyne",
        relation_type="works_on",
        properties={},
        created_at="",
    ))
    kg.close()

    wiki_root = tmp_path / "wiki"
    maintainer = LLMWikiMaintainer(wiki_root)
    update = maintainer.rebuild_from_graph(db_path)
    alice_page = wiki_root / "entities" / "person" / "alice.md"
    assert alice_page in update.paths
    with alice_page.open("a", encoding="utf-8") as fh:
        fh.write("Manual note survives.\n")

    maintainer.rebuild_from_graph(db_path)
    text = alice_page.read_text(encoding="utf-8")
    assert "Manual note survives." in text
    assert "works_on" in text


def test_wiki_cli_status_lint_and_rebuild_json(tmp_path, capsys):
    from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph
    from mnemosyne.wiki.cli import main

    db_path = tmp_path / "kg.db"
    kg = KnowledgeGraph(str(db_path))
    kg.add_entity(Entity(
        id="alice",
        type="person",
        name="Alice",
        properties={"source_file": "graph://demo", "source_files": ["graph://demo"]},
        created_at="",
        updated_at="",
    ))
    kg.close()

    wiki_root = tmp_path / "wiki"
    assert main(["rebuild", "--wiki-root", str(wiki_root), "--db-path", str(db_path), "--format", "json"]) == 0
    rebuild_out = capsys.readouterr().out
    assert '"count"' in rebuild_out

    assert main(["status", "--wiki-root", str(wiki_root), "--db-path", str(db_path), "--format", "json"]) == 0
    status_out = capsys.readouterr().out
    assert '"entity_pages": 1' in status_out

    assert main(["lint", "--wiki-root", str(wiki_root), "--db-path", str(db_path), "--format", "json"]) == 0
    lint_out = capsys.readouterr().out
    assert '"ok": true' in lint_out


def test_generated_pages_explain_editor_safe_manual_note_boundaries(tmp_path):
    source = tmp_path / "meeting.md"
    source.write_text("Alice works on Mnemosyne.", encoding="utf-8")
    wiki_root = tmp_path / "wiki"

    LLMWikiMaintainer(wiki_root).update_from_ingest(
        _parsed(),
        source=str(source),
        domain="daily",
        raw_path=source,
    )

    for page in (
        wiki_root / "index.md",
        wiki_root / "sources" / "daily" / "meeting.md",
        wiki_root / "entities" / "person" / "alice.md",
    ):
        text = page.read_text(encoding="utf-8")
        assert "## Editing guidance" in text
        assert "This generated section is replaced" in text
        assert "Add human notes outside the `MNEMOSYNE:GENERATED` markers" in text
        assert "Raw sources plus the graph database remain authoritative" in text


def test_editor_neutral_folder_shape_smoke_fixture(tmp_path):
    source = tmp_path / "meeting.md"
    source.write_text("Alice works on Mnemosyne.", encoding="utf-8")
    wiki_root = tmp_path / "wiki"

    LLMWikiMaintainer(wiki_root).update_from_ingest(
        _parsed(),
        source=str(source),
        domain="daily",
        scope_id="editor-smoke",
        source_channel="cli",
        raw_path=source,
    )

    expected = {
        "index.md",
        "log.md",
        "sources/daily/meeting.md",
        "entities/person/alice.md",
        "entities/project/mnemosyne.md",
    }
    actual = {path.relative_to(wiki_root).as_posix() for path in wiki_root.rglob("*.md")}
    assert expected <= actual

    for rel in expected:
        text = (wiki_root / rel).read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "page_type:" in text
        if rel != "log.md":
            assert text.count("<!-- MNEMOSYNE:GENERATED:START -->") == 1
            assert text.count("<!-- MNEMOSYNE:GENERATED:END -->") == 1
            assert "## Editing guidance" in text

    index = (wiki_root / "index.md").read_text(encoding="utf-8")
    source_page = (wiki_root / "sources" / "daily" / "meeting.md").read_text(encoding="utf-8")
    entity_page = (wiki_root / "entities" / "person" / "alice.md").read_text(encoding="utf-8")
    assert "[[entities/person/alice|Alice]]" in index
    assert "[[sources/daily/meeting|meeting.md]]" in index
    assert "[[entities/person/alice|Alice]]" in source_page
    assert "[[sources/daily/meeting|meeting.md]]" in entity_page


def test_wiki_write_lock_creates_metadata_and_releases(tmp_path):
    import os

    from mnemosyne.wiki.llm_wiki import WikiWriteLock

    wiki_root = tmp_path / "wiki"
    lock_path = wiki_root / ".mnemosyne-wiki.lock"

    with WikiWriteLock(wiki_root, action="unit-test"):
        assert lock_path.exists()
        metadata = LLMWikiMaintainer(wiki_root).lock_metadata()
        assert metadata["pid"] == os.getpid()
        assert metadata["action"] == "unit-test"
        assert metadata["wiki_root"] == str(wiki_root)
        assert metadata["owner_token"]

    assert not lock_path.exists()


def test_wiki_write_lock_timeout_and_stale_detection(tmp_path):
    import json
    from datetime import datetime, timedelta, timezone

    import pytest

    from mnemosyne.wiki.llm_wiki import WikiLockError, WikiWriteLock

    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()
    lock_path = wiki_root / ".mnemosyne-wiki.lock"
    lock_path.write_text(
        json.dumps({
            "owner_token": "other",
            "pid": 999999,
            "hostname": "test-host",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "action": "held-by-test",
            "wiki_root": str(wiki_root),
        }),
        encoding="utf-8",
    )

    with pytest.raises(WikiLockError) as exc_info:
        with WikiWriteLock(wiki_root, timeout_seconds=0, action="blocked"):
            pass

    assert exc_info.value.to_dict()["code"] == "wiki-lock-timeout"
    assert exc_info.value.to_dict()["lock_path"] == str(lock_path)
    assert exc_info.value.metadata["action"] == "held-by-test"
    assert LLMWikiMaintainer(wiki_root).is_lock_stale(max_age_seconds=60)


def test_wiki_write_lock_does_not_remove_foreign_lock(tmp_path):
    import json

    from mnemosyne.wiki.llm_wiki import WikiWriteLock

    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()
    lock_path = wiki_root / ".mnemosyne-wiki.lock"

    lock = WikiWriteLock(wiki_root, timeout_seconds=0, action="owner")
    lock.__enter__()
    lock_path.write_text(
        json.dumps({
            "owner_token": "foreign-owner",
            "pid": 123,
            "hostname": "elsewhere",
            "created_at": "2026-05-03T00:00:00+00:00",
            "action": "foreign",
            "wiki_root": str(wiki_root),
        }),
        encoding="utf-8",
    )

    lock.release()

    assert lock_path.exists()
    assert WikiWriteLock.read_metadata(lock_path)["owner_token"] == "foreign-owner"


def test_locked_rebuild_reports_json_error_without_corrupting_pages(tmp_path, capsys):
    from mnemosyne.graph.knowledge_graph import Entity, KnowledgeGraph
    from mnemosyne.wiki.cli import main

    db_path = tmp_path / "kg.db"
    kg = KnowledgeGraph(str(db_path))
    kg.add_entity(Entity(
        id="alice",
        type="person",
        name="Alice",
        properties={"source_file": "graph://demo", "source_files": ["graph://demo"]},
        created_at="",
        updated_at="",
    ))
    kg.close()

    wiki_root = tmp_path / "wiki"
    maintainer = LLMWikiMaintainer(wiki_root)
    maintainer.rebuild_from_graph(db_path)
    alice_page = wiki_root / "entities" / "person" / "alice.md"
    before = alice_page.read_text(encoding="utf-8")

    with maintainer.write_lock("held-by-test"):
        code = main([
            "rebuild",
            "--wiki-root",
            str(wiki_root),
            "--db-path",
            str(db_path),
            "--format",
            "json",
            "--lock-timeout",
            "0",
        ])

    captured = capsys.readouterr()
    assert code == 1
    assert '"code": "wiki-lock-timeout"' in captured.err
    assert str(wiki_root / ".mnemosyne-wiki.lock") in captured.err
    assert alice_page.read_text(encoding="utf-8") == before


def test_wiki_write_lock_with_custom_lock_dir(tmp_path, monkeypatch):
    import os
    import uuid
    from mnemosyne.wiki.llm_wiki import WikiWriteLock

    wiki_root = tmp_path / "wiki"
    lock_dir = tmp_path / "custom_lock_dir"
    monkeypatch.setenv("MNEMOSYNE_LOCK_DIR", str(lock_dir))

    root_hash = uuid.uuid5(uuid.NAMESPACE_DNS, str(wiki_root)).hex[:12]
    expected_lock_path = lock_dir / f".mnemosyne-wiki-{root_hash}.lock"

    with WikiWriteLock(wiki_root, action="unit-test-custom"):
        assert expected_lock_path.exists()
        assert not (wiki_root / ".mnemosyne-wiki.lock").exists()
        metadata = WikiWriteLock.read_metadata(expected_lock_path)
        assert metadata["pid"] == os.getpid()
        assert metadata["action"] == "unit-test-custom"

    assert not expected_lock_path.exists()

"""Focused tests for the local Obsidian vault boundary."""

from pathlib import Path

import pytest

from mnemosyne.obsidian import (
    ObsidianSyncConfig,
    ObsidianSyncError,
    inspect_vault,
    sync_file,
    sync_vault,
)


def _config(vault: Path, tmp_path: Path, **overrides) -> ObsidianSyncConfig:
    values = {
        "vault_root": vault,
        "db_path": tmp_path / "personal" / "graph" / "knowledge.db",
        "raw_root": tmp_path / "personal" / "raw",
        "dry_run": True,
    }
    values.update(overrides)
    return ObsidianSyncConfig(**values)


def test_sync_skips_obsidian_metadata_and_generated_wiki(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Notes").mkdir(parents=True)
    (vault / ".obsidian").mkdir()
    (vault / "_MnemosyneWiki").mkdir()
    (vault / "_private-export").mkdir()
    (vault / "Notes" / "today.md").write_text("# Today\nA useful note", encoding="utf-8")
    (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (vault / "_MnemosyneWiki" / "generated.md").write_text("generated", encoding="utf-8")
    (vault / "_private-export" / "ignored.md").write_text("ignored", encoding="utf-8")

    stats = sync_vault(_config(vault, tmp_path, exclude_dirs=("_private-export",)))

    assert stats.total == 1
    assert stats.new_files == 1
    assert [Path(result.source).name for result in stats.results] == ["today.md"]


def test_stats_only_reports_changes_without_extracting(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("one", encoding="utf-8")

    stats = inspect_vault(_config(vault, tmp_path))

    assert stats.total == 1
    assert stats.new_files == 1
    assert stats.results == []


def test_storage_roots_must_stay_outside_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ObsidianSyncError, match="db-path"):
        sync_vault(_config(vault, tmp_path, db_path=vault / "knowledge.db"))

    with pytest.raises(ObsidianSyncError, match="raw-root"):
        sync_vault(_config(vault, tmp_path, raw_root=vault / "raw"))


def test_sync_file_uses_same_boundary_as_vault_sync(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Notes").mkdir(parents=True)
    (vault / "_MnemosyneWiki").mkdir()
    note = vault / "Notes" / "current.md"
    note.write_text("# Current\nSynthetic note", encoding="utf-8")

    result = sync_file(_config(vault, tmp_path), note)

    assert result.source.endswith("/Notes/current.md")
    assert result.skipped is False
    with pytest.raises(ObsidianSyncError, match="inside the Obsidian vault"):
        sync_file(_config(vault, tmp_path), tmp_path / "outside.md")


def test_cli_parser_exposes_obsidian_sync_contract():
    from mnemosyne.cli import _run_sync_obsidian, build_parser

    args = build_parser().parse_args([
        "sync",
        "obsidian",
        "/tmp/vault",
        "--db-path",
        "/tmp/personal/knowledge.db",
        "--raw-root",
        "/tmp/personal/raw",
    ])

    assert args.func is _run_sync_obsidian
    assert args.scope_id == "personal"
    assert args.source_channel == "obsidian"
    assert args.wiki_root is None

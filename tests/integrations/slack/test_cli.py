"""Contract §9 / §11 T-CLI — parser shape, exit codes, and output hygiene."""

from __future__ import annotations

import json

import pytest

from mnemosyne.integrations.slack.cli import (
    EXIT_CREDENTIAL,
    EXIT_DENIED,
    EXIT_LIVE_BLOCKED,
    EXIT_NOT_FOUND,
    EXIT_OK,
    build_parser,
    main,
)
from mnemosyne.integrations.slack.config import DEFAULT_TOKEN_ENV
from mnemosyne.integrations.slack.identity import message_key_for_source

from .conftest import CHANNEL_ID, SCOPE_ID, SOURCE_ID, TEAM_ID, mk_ts


def run(capsys, db_path, *argv) -> tuple[int, dict]:
    """Invoke the CLI and return (exit_code, parsed_json_output)."""
    code = main(["--db-path", str(db_path), *argv])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip() else {})


@pytest.fixture
def prepared(db_path):
    """A registered source in a temporary database."""
    from mnemosyne.integrations.slack.store import SlackStore

    store = SlackStore(db_path)
    store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID)
    store.close()
    return db_path


# ── Parser ────────────────────────────────────────────────────────────

def test_parser_exposes_every_contracted_command():
    """T-CLI (smoke): the parser builds and carries the full surface."""
    parser = build_parser()
    sub = next(
        a for a in parser._actions if isinstance(a.choices, dict) and "sync" in a.choices
    )
    assert set(sub.choices) == {
        "init", "source", "sync", "reconcile", "status", "quarantine",
        "query", "purge",
    }


def test_parser_requires_a_command():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


@pytest.mark.parametrize(
    "argv",
    [
        ["sync"],                                   # missing --source-id
        ["reconcile", "--source-id", "s"],          # missing --since
        ["source", "register", "--team-id", "T"],   # missing channel/scope
        ["quarantine", "resolve", "--source-doc-id", "d"],
        ["query"],
    ],
)
def test_missing_required_arguments_are_rejected(argv):
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_sync_rejects_an_unknown_connector():
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["sync", "--source-id", "s", "--connector", "carrier-pigeon"]
        )


# ── Source management ─────────────────────────────────────────────────

def test_register_then_list(capsys, db_path):
    """T-CLI-1."""
    code, payload = run(
        capsys, db_path, "source", "register",
        "--team-id", TEAM_ID, "--channel-id", CHANNEL_ID, "--scope-id", SCOPE_ID,
    )
    assert code == EXIT_OK
    assert payload == {"source_id": SOURCE_ID, "status": "registered"}

    code, payload = run(capsys, db_path, "source", "list")
    assert code == EXIT_OK
    assert [s["source_id"] for s in payload["sources"]] == [SOURCE_ID]
    assert payload["sources"][0]["last_watermark"] == ""


def test_revoke_unknown_source_is_not_found(capsys, db_path):
    code, payload = run(
        capsys, db_path, "source", "revoke",
        "--source-id", "slack:T0FIXTURE:C0GONE", "--reason", "cleanup",
    )
    assert code == EXIT_NOT_FOUND
    assert payload["error"] == "deny:source_unregistered"


def test_init_registers_configured_sources(capsys, db_path, tmp_path):
    config = tmp_path / "slack.yaml"
    config.write_text(
        "token_env: MNEMOSYNE_SLACK_BOT_TOKEN\n"
        "sources:\n"
        f"  - team_id: {TEAM_ID}\n"
        f"    channel_id: {CHANNEL_ID}\n"
        f"    scope_id: {SCOPE_ID}\n",
        encoding="utf-8",
    )
    code, payload = run(capsys, db_path, "--config", str(config), "init")
    assert code == EXIT_OK
    assert payload["registered"] == [SOURCE_ID]
    assert payload["token_env"] == DEFAULT_TOKEN_ENV


# ── Sync / query ──────────────────────────────────────────────────────

def test_synthetic_sync_reports_a_full_summary(capsys, prepared, fixture_file):
    """T-CLI-2."""
    code, payload = run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture_file),
    )
    assert code == EXIT_OK
    assert set(payload) == {
        "source_id", "total", "ingested", "updated", "noop", "tombstoned",
        "quarantined", "rejected", "failed", "watermark", "errors",
    }
    assert payload["ingested"] == 12
    assert payload["watermark"] == mk_ts(11)


def test_mock_connector_sync_works_end_to_end(capsys, prepared, fixture_file):
    code, payload = run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID,
        "--connector", "mock", "--fixture", str(fixture_file),
    )
    assert code == EXIT_OK
    assert payload["ingested"] == 12


def test_sync_without_a_fixture_reports_not_found(capsys, prepared):
    code, payload = run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID, "--connector", "synthetic"
    )
    assert code == EXIT_NOT_FOUND
    assert "--fixture" in payload["detail"]


def test_sync_of_an_unregistered_source_is_not_found(capsys, db_path, fixture_file):
    code, payload = run(
        capsys, db_path, "sync", "--source-id", "slack:T0FIXTURE:C0GONE",
        "--connector", "synthetic", "--fixture", str(fixture_file),
    )
    assert code == EXIT_NOT_FOUND
    assert payload["error"] == "deny:source_unregistered"


def test_query_returns_stored_messages(capsys, prepared, fixture_file):
    run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture_file),
    )
    code, payload = run(capsys, prepared, "query", "--source-id", SOURCE_ID)
    assert code == EXIT_OK
    assert payload["count"] == 12
    assert payload["scope_id"] == SCOPE_ID
    assert payload["results"][0]["ts"] == mk_ts(0)


def test_query_by_thread_reports_root_state(capsys, prepared, fixture_file):
    run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture_file),
    )
    code, payload = run(
        capsys, prepared, "query", "--source-id", SOURCE_ID, "--thread-ts", mk_ts(4)
    )
    assert code == EXIT_OK
    assert payload["count"] == 4
    assert payload["thread_root_tombstoned"] is False


def test_query_grep_filters(capsys, prepared, fixture_file):
    run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture_file),
    )
    code, payload = run(
        capsys, prepared, "query", "--source-id", SOURCE_ID, "--grep", "root 4"
    )
    assert code == EXIT_OK
    assert payload["count"] == 1


def test_query_excludes_tombstoned_by_default(capsys, prepared, fixture_file):
    from mnemosyne.integrations.slack.store import SlackStore

    run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture_file),
    )
    store = SlackStore(prepared)
    store.tombstone_message(
        message_key_for_source(SOURCE_ID, mk_ts(0)), "reconcile:remote_absent"
    )
    store.close()

    _, default = run(capsys, prepared, "query", "--source-id", SOURCE_ID)
    _, included = run(
        capsys, prepared, "query", "--source-id", SOURCE_ID, "--include-tombstoned"
    )
    assert default["count"] == 11
    assert included["count"] == 12


def test_query_of_a_revoked_source_is_denied(capsys, prepared, fixture_file):
    run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture_file),
    )
    run(capsys, prepared, "source", "revoke", "--source-id", SOURCE_ID,
        "--reason", "offboarded")
    code, payload = run(capsys, prepared, "query", "--source-id", SOURCE_ID)
    assert code == EXIT_DENIED
    assert payload["error"] == "deny:source_revoked"


def test_quarantined_sync_exits_denied(capsys, db_path, tmp_path):
    from mnemosyne.integrations.slack.store import SlackStore

    from .conftest import build_fixture, public_channel

    store = SlackStore(db_path)
    store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID)
    store.close()

    fixture = tmp_path / "private.json"
    fixture.write_text(
        json.dumps(build_fixture(info=public_channel(is_private=True))),
        encoding="utf-8",
    )
    code, payload = run(
        capsys, db_path, "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture),
    )
    assert code == EXIT_DENIED
    assert payload["quarantined"] == 1
    assert payload["ingested"] == 0


# ── Live block ────────────────────────────────────────────────────────

def test_live_connector_is_blocked(capsys, prepared, monkeypatch):
    """T-CLI-3 / R35: expected behaviour in v1, exit code 5."""
    monkeypatch.setenv(DEFAULT_TOKEN_ENV, "xoxb-not-real")
    code, payload = run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID, "--connector", "live"
    )
    assert code == EXIT_LIVE_BLOCKED
    assert payload["error"] == "blocked:live_not_approved"


def test_live_connector_without_a_token_is_a_credential_error(
    capsys, prepared, monkeypatch
):
    monkeypatch.delenv(DEFAULT_TOKEN_ENV, raising=False)
    code, payload = run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID, "--connector", "live"
    )
    assert code == EXIT_CREDENTIAL
    assert payload["error"] == "blocked:credential_missing"


def test_cli_output_never_prints_a_token(capsys, prepared, monkeypatch):
    """T-CR-6 on the CLI surface."""
    token = "xoxb-9999-SHOULDNOTAPPEAR"
    monkeypatch.setenv(DEFAULT_TOKEN_ENV, token)
    main(["--db-path", str(prepared), "sync", "--source-id", SOURCE_ID,
          "--connector", "live"])
    assert token not in capsys.readouterr().out


# ── Destructive command ───────────────────────────────────────────────

def test_purge_requires_confirmation(capsys, prepared, fixture_file):
    """T-CLI-4."""
    run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture_file),
    )
    code, payload = run(capsys, prepared, "purge", "--source-id", SOURCE_ID)
    assert code == EXIT_DENIED
    assert payload["error"] == "deny:confirmation_required"

    _, still_there = run(capsys, prepared, "query", "--source-id", SOURCE_ID)
    assert still_there["count"] == 12


def test_purge_with_confirmation_removes_everything(capsys, prepared, fixture_file):
    run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture_file),
    )
    code, payload = run(
        capsys, prepared, "purge", "--source-id", SOURCE_ID, "--confirm"
    )
    assert code == EXIT_OK
    assert payload["rows_removed"] >= 13

    code, _ = run(capsys, prepared, "query", "--source-id", SOURCE_ID)
    assert code == EXIT_NOT_FOUND


# ── Quarantine ────────────────────────────────────────────────────────

def test_quarantine_resolve_requires_an_actor():
    """T-CLI-5: argparse refuses before any state is touched."""
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "quarantine", "resolve", "--source-doc-id", SOURCE_ID,
            "--source-id", SOURCE_ID, "--resolution", "replayed", "--reason", "r",
        ])


def test_quarantine_list_and_resolve(capsys, db_path, tmp_path):
    from mnemosyne.integrations.slack.store import SlackStore

    from .conftest import build_fixture, public_channel

    store = SlackStore(db_path)
    store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID)
    store.close()

    fixture = tmp_path / "private.json"
    fixture.write_text(
        json.dumps(build_fixture(info=public_channel(is_private=True))),
        encoding="utf-8",
    )
    run(capsys, db_path, "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture))

    code, payload = run(capsys, db_path, "quarantine", "list")
    assert code == EXIT_OK
    assert payload["quarantine"][0]["reason"] == "quarantine:deny:channel_type"
    assert "text" not in json.dumps(payload["quarantine"][0]["snapshot"])

    code, payload = run(
        capsys, db_path, "quarantine", "resolve",
        "--source-doc-id", SOURCE_ID, "--source-id", SOURCE_ID,
        "--actor", "alice", "--resolution", "rejected", "--reason", "private channel",
    )
    assert code == EXIT_OK
    assert payload["resolved"] is True


def test_status_reports_checkpoint_and_quarantine(capsys, prepared, fixture_file):
    run(
        capsys, prepared, "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture_file),
    )
    code, payload = run(capsys, prepared, "status")
    assert code == EXIT_OK
    assert payload["quarantine_pending"] == 0
    assert payload["sources"][0]["last_watermark"] == mk_ts(11)
    assert payload["sources"][0]["documents_processed"] == 12

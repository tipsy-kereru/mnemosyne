"""Regression tests for validation findings V-01, V-02, V-03.

Source: ``.orca-orchestrator/VALIDATION_SLACK_SECURITY_REVIEW.md``.

Each test asserts the *durable consequence* the contract requires — a
quarantine record, a source status, an untouched watermark — rather than
that an exception was raised. The original T-MK-4 passed while the gate
it named did not hold precisely because it stopped at the exception.
"""

from __future__ import annotations

import json

import pytest

from mnemosyne.integrations.slack import api as api_mod
from mnemosyne.integrations.slack.api import (
    CODE_MISSING_SCOPE_HEADER,
    SlackLiveBlocked,
    WebApiConnector,
    enforce_scope_header,
)
from mnemosyne.integrations.slack.cli import EXIT_DENIED, EXIT_ERROR
from mnemosyne.integrations.slack.cli import main as cli_main
from mnemosyne.integrations.slack.config import (
    CODE_OVERBROAD_SCOPE,
    REQUIRED_SCOPES,
    SlackScopeError,
)
from mnemosyne.integrations.slack.connector import SyntheticConnector
from mnemosyne.integrations.slack.identity import message_key_for_source
from mnemosyne.integrations.slack.mock_api import MockSlackServer
from mnemosyne.integrations.slack.store import (
    SOURCE_QUARANTINED,
    SOURCE_REGISTERED,
    SlackStore,
)
from mnemosyne.integrations.slack.sync import (
    RECONCILE_MALFORMED_REMOTE,
    QUARANTINE_API_ERRORS,
    SlackSyncEngine,
)

from .conftest import (
    CHANNEL_ID,
    SCOPE_ID,
    SOURCE_ID,
    TEAM_ID,
    build_fixture,
    mk_ts,
)

TOKEN = "xoxb-test"


def http_engine(store, srv):
    return SlackSyncEngine(
        store,
        WebApiConnector(
            TOKEN, base_url=srv.base_url, max_retries=1, initial_backoff=0
        ),
    )


# ══ V-01 ═══════════════════════════════════════════════════════════════
# A connector error during the ACL phase must produce a durable
# quarantine record and stop the fetch — not propagate uncaught leaving
# no trace.

@pytest.mark.parametrize("error", sorted(QUARANTINE_API_ERRORS - {"channel_not_found"}))
def test_v01_permission_error_quarantines_with_state(registered_store, fixture_data, error):
    srv = MockSlackServer(
        fixture=fixture_data, expected_token=TOKEN, channel_error=error
    )
    srv.start()
    try:
        result = http_engine(registered_store, srv).sync(SOURCE_ID)
    finally:
        srv.stop()

    assert result.quarantined == 1
    assert result.ingested == 0
    assert error in result.errors

    records = registered_store.list_quarantine()
    assert len(records) == 1
    assert records[0].reason == f"quarantine:{error}"

    source = registered_store.get_source(SOURCE_ID)
    assert source.status == SOURCE_QUARANTINED
    assert error in source.last_error

    # No fetch happened.
    assert "conversations.history" not in srv.requests
    assert registered_store.list_messages(SOURCE_ID) == []


def test_v01_channel_not_found_quarantines(registered_store, fixture_data):
    srv = MockSlackServer(fixture=fixture_data, expected_token=TOKEN)
    srv.start()
    try:
        # The source is registered but the fixture has no such channel.
        registered_store.conn.execute(
            "UPDATE slack_source SET channel_id='C0ABSENT' WHERE source_id=?",
            (SOURCE_ID,),
        )
        registered_store.conn.commit()
        result = http_engine(registered_store, srv).sync(SOURCE_ID)
    finally:
        srv.stop()

    assert result.quarantined == 1
    assert registered_store.get_source(SOURCE_ID).status == SOURCE_QUARANTINED
    assert registered_store.list_quarantine()[0].reason == "quarantine:channel_not_found"


def test_v01_quarantine_record_stays_metadata_only(registered_store):
    """The record must not gain a body just because the path changed."""
    secret = "CONFIDENTIAL-BODY"
    fixture = build_fixture(
        messages=[{"ts": mk_ts(0), "user": "U1", "text": secret}]
    )
    srv = MockSlackServer(
        fixture=fixture, expected_token=TOKEN, channel_error="not_in_channel"
    )
    srv.start()
    try:
        http_engine(registered_store, srv).sync(SOURCE_ID)
    finally:
        srv.stop()

    snapshot = registered_store.list_quarantine()[0].snapshot
    blob = json.dumps(snapshot)
    assert secret not in blob
    assert "members" not in snapshot
    assert set(snapshot) <= {"source_id", "team_id", "reason"}


def test_v01_synthetic_missing_channel_quarantines(registered_store):
    """A connector raising LookupError is treated as channel_not_found."""
    fixture = {"team_id": TEAM_ID, "channels": {}}
    result = SlackSyncEngine(
        registered_store, SyntheticConnector(fixture)
    ).sync(SOURCE_ID)

    assert result.quarantined == 1
    assert registered_store.get_source(SOURCE_ID).status == SOURCE_QUARANTINED


def test_v01_auth_failure_is_a_run_failure_not_a_quarantine(
    registered_store, fixture_data
):
    """invalid_auth is an operator problem; blaming the channel would be wrong."""
    srv = MockSlackServer(fixture=fixture_data, expected_token="xoxb-different")
    srv.start()
    try:
        result = http_engine(registered_store, srv).sync(SOURCE_ID)
    finally:
        srv.stop()

    assert result.failed == 1
    assert result.quarantined == 0
    assert "invalid_auth" in result.errors
    assert registered_store.list_quarantine() == []

    source = registered_store.get_source(SOURCE_ID)
    assert source.status == SOURCE_REGISTERED
    assert "invalid_auth" in source.last_error
    assert "conversations.history" not in srv.requests


def test_v01_acl_failure_preserves_the_watermark(registered_store, fixture_data):
    engine = SlackSyncEngine(registered_store, SyntheticConnector(fixture_data))
    engine.sync(SOURCE_ID)
    before = registered_store.get_source(SOURCE_ID).last_watermark
    assert before == mk_ts(11)

    srv = MockSlackServer(
        fixture=fixture_data, expected_token=TOKEN, channel_error="is_archived"
    )
    srv.start()
    try:
        result = http_engine(registered_store, srv).sync(SOURCE_ID)
    finally:
        srv.stop()

    assert result.watermark == before
    assert registered_store.get_source(SOURCE_ID).last_watermark == before


def test_v01_reconcile_also_quarantines(registered_store, fixture_data):
    srv = MockSlackServer(
        fixture=fixture_data, expected_token=TOKEN, channel_error="not_in_channel"
    )
    srv.start()
    try:
        result = http_engine(registered_store, srv).reconcile(
            SOURCE_ID, since=mk_ts(0)
        )
    finally:
        srv.stop()

    assert result.quarantined == 1
    assert result.tombstoned == 0
    assert registered_store.get_source(SOURCE_ID).status == SOURCE_QUARANTINED


def test_v01_live_block_still_propagates(registered_store):
    """The broad catch must not swallow our own refusal to act."""
    engine = SlackSyncEngine(registered_store, WebApiConnector(TOKEN))
    with pytest.raises(SlackLiveBlocked):
        engine.sync(SOURCE_ID)
    assert registered_store.list_quarantine() == []
    assert registered_store.get_source(SOURCE_ID).status == SOURCE_REGISTERED


class _BrokenConnector:
    """Fails the ACL call with an error that is nobody's policy decision."""

    calls: list[str] = []

    def channel_info(self, channel_id):
        raise RuntimeError("connector exploded")

    def history(self, channel_id, *, oldest="", limit=200):  # pragma: no cover
        raise AssertionError("history must not be called after an ACL failure")

    def replies(self, channel_id, thread_ts, *, oldest=""):  # pragma: no cover
        raise AssertionError("replies must not be called after an ACL failure")


def test_v01_cli_reports_a_quarantine_as_denied(capsys, db_path, tmp_path):
    """Exit 2, and the summary still prints rather than a traceback."""
    store = SlackStore(db_path)
    store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID)
    store.close()

    empty = tmp_path / "no_channel.json"
    empty.write_text(json.dumps({"team_id": TEAM_ID, "channels": {}}))

    code = cli_main([
        "--db-path", str(db_path), "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(empty),
    ])
    assert code == EXIT_DENIED
    payload = json.loads(capsys.readouterr().out)
    assert payload["quarantined"] == 1
    assert payload["ingested"] == 0


def test_v01_cli_reports_a_connector_failure_as_error(
    capsys, db_path, fixture_file, monkeypatch
):
    """A swallowed connector failure must not exit 0."""
    import mnemosyne.integrations.slack.cli as cli_mod

    store = SlackStore(db_path)
    store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID)
    store.close()

    monkeypatch.setattr(
        cli_mod._ConnectorSession, "__enter__", lambda self: _BrokenConnector()
    )
    code = cli_main([
        "--db-path", str(db_path), "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture_file),
    ])
    assert code == EXIT_ERROR
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
    assert payload["quarantined"] == 0


# ══ V-02 ═══════════════════════════════════════════════════════════════
# A malformed remote timestamp must abort reconcile before any tombstone
# or watermark movement: absence may never be inferred from degraded data.

def test_v02_malformed_remote_ts_aborts_reconcile(registered_store):
    good = [
        {"ts": mk_ts(0), "user": "U1", "text": "a"},
        {"ts": mk_ts(1), "user": "U1", "text": "b"},
    ]
    SlackSyncEngine(
        registered_store, SyntheticConnector(build_fixture(messages=good))
    ).sync(SOURCE_ID)
    before = registered_store.get_source(SOURCE_ID).last_watermark
    assert len(registered_store.list_messages(SOURCE_ID)) == 2

    corrupt = [
        {"ts": mk_ts(0), "user": "U1", "text": "a"},
        {"ts": "BAD-TS", "user": "U1", "text": "b"},
    ]
    result = SlackSyncEngine(
        registered_store, SyntheticConnector(build_fixture(messages=corrupt))
    ).reconcile(SOURCE_ID, since=mk_ts(0))

    assert result.tombstoned == 0
    assert result.failed == 1
    assert result.watermark == before
    assert registered_store.get_source(SOURCE_ID).last_watermark == before

    # The message that "went missing" only because its ts was unusable
    # must still be live.
    still_live = registered_store.get_message(
        message_key_for_source(SOURCE_ID, mk_ts(1))
    )
    assert still_live.tombstoned is False
    assert len(registered_store.list_messages(SOURCE_ID)) == 2

    assert RECONCILE_MALFORMED_REMOTE in registered_store.get_source(
        SOURCE_ID
    ).last_error


def test_v02_abort_happens_before_any_write(registered_store):
    """Not one message is updated when the batch is unusable."""
    good = [{"ts": mk_ts(0), "user": "U1", "text": "original"}]
    SlackSyncEngine(
        registered_store, SyntheticConnector(build_fixture(messages=good))
    ).sync(SOURCE_ID)

    corrupt = [
        {"ts": mk_ts(0), "user": "U1", "text": "EDITED"},
        {"ts": "BAD-TS", "user": "U1", "text": "junk"},
    ]
    result = SlackSyncEngine(
        registered_store, SyntheticConnector(build_fixture(messages=corrupt))
    ).reconcile(SOURCE_ID, since=mk_ts(0))

    assert result.updated == 0
    stored = registered_store.get_message(
        message_key_for_source(SOURCE_ID, mk_ts(0))
    )
    assert stored.text == "original"
    assert stored.version == 1


def test_v02_aborted_reconcile_exits_nonzero(capsys, db_path, tmp_path):
    """A reconcile that refused to run must not report success.

    Found in revalidation: the abort was counted as a per-item
    ``rejected``, which the CLI does not escalate, so ``reconcile &&
    next-step`` would carry on as though reconciliation had completed.
    The safety properties are asserted here too, so a future change
    cannot buy the exit code back by weakening the abort.
    """
    store = SlackStore(db_path)
    store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID)
    good = [
        {"ts": mk_ts(0), "user": "U1", "text": "a"},
        {"ts": mk_ts(1), "user": "U1", "text": "b"},
    ]
    SlackSyncEngine(store, SyntheticConnector(build_fixture(messages=good))).sync(
        SOURCE_ID
    )
    before = store.get_source(SOURCE_ID).last_watermark
    store.close()

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text(json.dumps(build_fixture(messages=[
        {"ts": mk_ts(0), "user": "U1", "text": "a"},
        {"ts": "NOT-A-TS", "user": "U1", "text": "b"},
    ])))

    code = cli_main([
        "--db-path", str(db_path), "reconcile", "--source-id", SOURCE_ID,
        "--since", mk_ts(0), "--connector", "synthetic", "--fixture", str(corrupt),
    ])
    payload = json.loads(capsys.readouterr().out)

    assert code != 0
    assert code == EXIT_ERROR
    assert payload["failed"] == 1
    assert RECONCILE_MALFORMED_REMOTE in payload["errors"][0]

    # The abort still did nothing destructive.
    assert payload["tombstoned"] == 0
    assert payload["watermark"] == before
    store = SlackStore(db_path)
    try:
        assert store.get_source(SOURCE_ID).last_watermark == before
        assert len(store.list_messages(SOURCE_ID)) == 2
    finally:
        store.close()


def test_v02_successful_reconcile_still_exits_zero(capsys, db_path, fixture_file):
    """The escalation must not fire on a clean run."""
    store = SlackStore(db_path)
    store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID)
    store.close()

    cli_main([
        "--db-path", str(db_path), "sync", "--source-id", SOURCE_ID,
        "--connector", "synthetic", "--fixture", str(fixture_file),
    ])
    capsys.readouterr()

    code = cli_main([
        "--db-path", str(db_path), "reconcile", "--source-id", SOURCE_ID,
        "--since", mk_ts(0), "--connector", "synthetic", "--fixture", str(fixture_file),
    ])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["failed"] == 0
    assert payload["noop"] == 12


def test_v02_clean_reconcile_still_tombstones(registered_store):
    """The abort must not disable legitimate deletion detection."""
    good = [
        {"ts": mk_ts(0), "user": "U1", "text": "a"},
        {"ts": mk_ts(1), "user": "U1", "text": "b"},
    ]
    SlackSyncEngine(
        registered_store, SyntheticConnector(build_fixture(messages=good))
    ).sync(SOURCE_ID)

    result = SlackSyncEngine(
        registered_store, SyntheticConnector(build_fixture(messages=good[:1]))
    ).reconcile(SOURCE_ID, since=mk_ts(0))

    assert result.tombstoned == 1


# ══ V-03 ═══════════════════════════════════════════════════════════════
# A live response without X-OAuth-Scopes leaves nothing to check, so it
# must deny rather than pass.

def test_v03_missing_header_denies_for_live():
    with pytest.raises(SlackScopeError) as exc:
        enforce_scope_header(None, loopback=False)
    assert exc.value.code == CODE_MISSING_SCOPE_HEADER


def test_v03_missing_header_allowed_for_loopback():
    enforce_scope_header(None, loopback=True)


def test_v03_present_header_is_still_checked():
    enforce_scope_header(",".join(REQUIRED_SCOPES), loopback=False)
    with pytest.raises(SlackScopeError) as exc:
        enforce_scope_header("channels:read,groups:history", loopback=False)
    assert exc.value.code == CODE_OVERBROAD_SCOPE


def test_v03_empty_header_is_not_a_missing_header():
    """An empty value is a real answer: no scopes granted."""
    enforce_scope_header("", loopback=False)


def test_v03_stripped_header_rejected_over_http(fixture_data, monkeypatch):
    """A proxy that drops the header must not silently disable the guard."""
    srv = MockSlackServer(
        fixture=fixture_data, expected_token=TOKEN, send_scope_header=False
    )
    srv.start()
    try:
        monkeypatch.setattr(api_mod, "is_loopback", lambda url: False)
        connector = WebApiConnector(
            TOKEN, base_url=srv.base_url, max_retries=1, initial_backoff=0,
            live_approved=True,
        )
        with pytest.raises(SlackScopeError) as exc:
            connector.channel_info(CHANNEL_ID)
        assert exc.value.code == CODE_MISSING_SCOPE_HEADER
    finally:
        srv.stop()


def test_v03_stripped_header_tolerated_on_loopback(fixture_data):
    """The mock stays usable without the header."""
    srv = MockSlackServer(
        fixture=fixture_data, expected_token=TOKEN, send_scope_header=False
    )
    srv.start()
    try:
        connector = WebApiConnector(
            TOKEN, base_url=srv.base_url, max_retries=1, initial_backoff=0
        )
        assert connector.channel_info(CHANNEL_ID).channel_id == CHANNEL_ID
    finally:
        srv.stop()

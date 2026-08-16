"""Contract §11 T-MK — the Web API adapter against a loopback mock.

Every test here talks to an in-process HTTP server bound to 127.0.0.1.
Nothing reaches Slack: the adapter's live guard refuses any other host,
and that refusal is asserted in ``test_credentials.py``.
"""

from __future__ import annotations

import pytest

from mnemosyne.integrations.slack.api import SlackApiError, WebApiConnector
from mnemosyne.integrations.slack.config import SlackScopeError
from mnemosyne.integrations.slack.mock_api import MockSlackServer
from mnemosyne.integrations.slack.store import SOURCE_QUARANTINED
from mnemosyne.integrations.slack.sync import SlackSyncEngine

from .conftest import (
    CHANNEL_ID,
    SOURCE_ID,
    build_fixture,
    mk_ts,
    public_channel,
)

TOKEN = "xoxb-test"


@pytest.fixture
def server(fixture_data):
    srv = MockSlackServer(fixture=fixture_data, page_size=5)
    srv.start()
    yield srv
    srv.stop()


def connector(server, **kwargs) -> WebApiConnector:
    kwargs.setdefault("max_retries", 3)
    kwargs.setdefault("initial_backoff", 0.01)
    return WebApiConnector(TOKEN, base_url=server.base_url, **kwargs)


def test_mock_binds_loopback_only(server):
    """T-MK-5: the mock must never be reachable off-box."""
    assert server.base_url.startswith("http://127.0.0.1:")
    with pytest.raises(ValueError):
        MockSlackServer(host="0.0.0.0")


def test_pagination_returns_every_message(server):
    """T-MK-1: 12 messages over a page size of 5 is three pages."""
    messages = list(connector(server).history(CHANNEL_ID, limit=200))
    assert len(messages) == 12
    assert [m.ts for m in messages] == sorted(m.ts for m in messages)
    assert server.requests.count("conversations.history") == 3


def test_pagination_returns_every_member(server):
    server.fixture["channels"][CHANNEL_ID]["info"]["members"] = [
        f"U{i}" for i in range(12)
    ]
    info = connector(server).channel_info(CHANNEL_ID)
    assert len(info.members) == 12
    assert server.requests.count("conversations.members") == 3


def test_repeated_cursor_does_not_loop_forever(server, monkeypatch):
    """A misbehaving server must fail fast, not hang the run."""
    conn = connector(server)
    pages = [
        {"messages": [{"ts": mk_ts(0)}], "response_metadata": {"next_cursor": "5"}},
        {"messages": [{"ts": mk_ts(1)}], "response_metadata": {"next_cursor": "5"}},
    ]
    monkeypatch.setattr(conn, "_call", lambda m, p: pages[min(len(p), 1)])
    with pytest.raises(SlackApiError) as exc:
        list(conn._paginate("conversations.history", {}, "messages"))
    assert exc.value.code == "pagination_loop"


def test_rate_limit_is_retried_then_succeeds(server):
    """T-MK-2."""
    server.fail_first_n = 1
    server.fail_error = "ratelimited"
    info = connector(server).channel_info(CHANNEL_ID)
    assert info.channel_id == CHANNEL_ID
    assert server.request_count >= 2


def test_rate_limit_beyond_retries_gives_up(server):
    server.fail_first_n = 99
    server.fail_error = "ratelimited"
    with pytest.raises(SlackApiError) as exc:
        connector(server, max_retries=2).channel_info(CHANNEL_ID)
    assert exc.value.code == "ratelimited"
    assert server.request_count == 2


def test_invalid_auth_is_not_retried(server):
    """T-MK-3: a wrong token is not a transient condition."""
    bad = WebApiConnector(
        "xoxb-wrong", base_url=server.base_url, max_retries=3, initial_backoff=0.01
    )
    with pytest.raises(SlackApiError) as exc:
        bad.channel_info(CHANNEL_ID)
    assert exc.value.code == "invalid_auth"
    assert server.request_count == 1


@pytest.mark.parametrize("error", ["not_in_channel", "is_archived", "restricted_action"])
def test_permission_errors_surface_for_quarantine(server, error):
    """T-MK-4: a permission failure must not be retried into success."""
    server.channel_error = error
    with pytest.raises(SlackApiError) as exc:
        connector(server).channel_info(CHANNEL_ID)
    assert exc.value.code == error
    assert server.request_count == 1


def test_unknown_channel_reports_channel_not_found(server):
    with pytest.raises(SlackApiError) as exc:
        connector(server).channel_info("C0MISSING")
    assert exc.value.code == "channel_not_found"


def test_overbroad_scope_header_aborts_before_using_the_response(server):
    """R30 enforced on the wire, not only on config."""
    server.granted_scopes = "channels:read,channels:history,groups:history"
    with pytest.raises(SlackScopeError) as exc:
        connector(server).channel_info(CHANNEL_ID)
    assert exc.value.code == "reject:overbroad_scope"


def test_oldest_bound_is_exclusive(server):
    """The protocol promises strictly-greater; Slack's oldest is inclusive."""
    messages = list(connector(server).history(CHANNEL_ID, oldest=mk_ts(5), limit=200))
    assert [m.ts for m in messages] == [mk_ts(n) for n in range(6, 12)]


def test_replies_returns_one_thread(server):
    root = mk_ts(4)
    messages = list(connector(server).replies(CHANNEL_ID, root))
    assert [m.ts for m in messages] == [mk_ts(4), mk_ts(5), mk_ts(6), mk_ts(7)]


def test_full_sync_over_the_mock_matches_the_synthetic_path(registered_store, server):
    """The mocked HTTP path and the offline path agree."""
    engine = SlackSyncEngine(registered_store, connector(server))
    result = engine.sync(SOURCE_ID)

    assert result.ingested == 12
    assert result.watermark == mk_ts(11)
    assert len(registered_store.list_messages(SOURCE_ID, limit=100)) == 12


def test_acl_gate_holds_over_http(registered_store):
    """A private channel is refused before any history request is made."""
    srv = MockSlackServer(
        fixture=build_fixture(info=public_channel(is_private=True)), page_size=5
    )
    srv.start()
    try:
        engine = SlackSyncEngine(registered_store, connector(srv))
        result = engine.sync(SOURCE_ID)
        assert result.quarantined == 1
        assert "conversations.history" not in srv.requests
        assert registered_store.get_source(SOURCE_ID).status == SOURCE_QUARANTINED
    finally:
        srv.stop()

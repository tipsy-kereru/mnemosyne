"""Contract §4 — fail-closed ACL and quarantine (T-ACL-1..6)."""

from __future__ import annotations

import json

import pytest

from mnemosyne.integrations.slack.acl import (
    DENY_ACL_EMPTY,
    DENY_ACL_MISSING,
    DENY_ACL_STALE,
    DENY_CHANNEL_TYPE,
    ChannelInfo,
    acl_denial,
    classify_channel,
    quarantine_snapshot,
)
from mnemosyne.integrations.slack.store import SOURCE_QUARANTINED, SlackStoreError

from .conftest import (
    CHANNEL_ID,
    SOURCE_ID,
    build_fixture,
    make_engine,
    public_channel,
    stale_iso,
    utc_now_iso,
)


def info(**overrides) -> ChannelInfo:
    base = dict(
        channel_id=CHANNEL_ID,
        members=["U1", "U2"],
        captured_at=utc_now_iso(),
    )
    base.update(overrides)
    return ChannelInfo(**base)


def test_public_channel_with_fresh_acl_is_allowed():
    """T-ACL-1."""
    assert acl_denial(info()) == ""
    assert classify_channel(info()) == "public_channel"


@pytest.mark.parametrize(
    "flag",
    ["is_private", "is_ext_shared", "is_org_shared", "is_im", "is_mpim"],
)
def test_non_public_channel_types_are_denied(flag):
    """T-ACL-2 / R13: five refusals, no inspection of contents."""
    assert acl_denial(info(**{flag: True})) == DENY_CHANNEL_TYPE


def test_acl_before_fetch_order_is_enforced(registered_store):
    """T-ACL-3 (core): a denied channel is never fetched from."""
    fixture = build_fixture(info=public_channel(is_private=True))
    engine = make_engine(registered_store, fixture)

    result = engine.sync(SOURCE_ID)

    calls = engine.connector.calls
    assert any(c.startswith("channel_info") for c in calls)
    assert not any(c.startswith(("history", "replies")) for c in calls)
    assert result.quarantined == 1
    assert result.ingested == 0


def test_allowed_channel_checks_acl_before_history(registered_store, fixture_data):
    """T-ACL-3 (order): channel_info must precede the first history call."""
    engine = make_engine(registered_store, fixture_data)
    engine.sync(SOURCE_ID)

    calls = engine.connector.calls
    first_info = next(i for i, c in enumerate(calls) if c.startswith("channel_info"))
    first_history = next(i for i, c in enumerate(calls) if c.startswith("history"))
    assert first_info < first_history


def test_stale_acl_snapshot_denies():
    """T-ACL-4 / R15: 25h old denies, 23h old passes."""
    assert acl_denial(info(captured_at=stale_iso(25))) == DENY_ACL_STALE
    assert acl_denial(info(captured_at=stale_iso(23))) == ""


def test_unparseable_capture_time_denies():
    assert acl_denial(info(captured_at="not-a-timestamp")) == DENY_ACL_STALE


def test_naive_capture_time_is_treated_as_utc_not_a_crash():
    """A naive timestamp must deny or allow — never raise."""
    from datetime import datetime, timezone

    naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    assert acl_denial(info(captured_at=naive)) == ""


def test_empty_member_list_denies():
    """T-ACL-5."""
    assert acl_denial(info(members=[])) == DENY_ACL_EMPTY


def test_never_captured_acl_denies_as_missing():
    assert acl_denial(info(members=[], captured_at=None)) == DENY_ACL_MISSING


def test_quarantine_snapshot_carries_no_content(registered_store):
    """T-ACL-6 / R16: metadata only, and a count instead of a member list."""
    fixture = build_fixture(
        info=public_channel(members=["U-SECRET"], is_private=True),
        messages=[{"ts": "1712345678.000100", "user": "U1", "text": "confidential"}],
    )
    engine = make_engine(registered_store, fixture)
    engine.sync(SOURCE_ID)

    records = registered_store.list_quarantine()
    assert len(records) == 1
    blob = json.dumps(records[0].snapshot)
    assert "confidential" not in blob
    assert "U-SECRET" not in blob
    assert records[0].snapshot["member_count"] == 1
    assert registered_store.get_source(SOURCE_ID).status == SOURCE_QUARANTINED


def test_quarantine_snapshot_builder_only_emits_allowed_keys():
    snapshot = quarantine_snapshot(info(), SOURCE_ID, "T0FIXTURE")
    assert "members" not in snapshot
    assert "text" not in snapshot
    assert snapshot["member_count"] == 2


def test_store_refuses_a_snapshot_carrying_a_body(registered_store):
    """R16 is enforced at the write, not only at the caller."""
    with pytest.raises(SlackStoreError) as exc:
        registered_store.quarantine(
            SOURCE_ID, SOURCE_ID, "quarantine:test", {"text": "leaked body"}
        )
    assert exc.value.code == "reject:quarantine_payload"


def test_store_refuses_a_token_shaped_snapshot_value(registered_store):
    with pytest.raises(SlackStoreError) as exc:
        registered_store.quarantine(
            SOURCE_ID, SOURCE_ID, "quarantine:test",
            {"channel_id": "xoxb-1234-abcd"},
        )
    assert exc.value.code == "reject:quarantine_payload"

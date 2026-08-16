"""Contract §5 — synthetic sync, reconcile, and checkpoint safety."""

from __future__ import annotations

import pytest

from mnemosyne.integrations.slack.store import SlackStoreError
from mnemosyne.integrations.slack.identity import message_key_for_source
from mnemosyne.integrations.slack.sync import (
    RECONCILE_REMOTE_ABSENT,
    safe_watermark,
)

from .conftest import (
    SOURCE_ID,
    build_fixture,
    make_engine,
    mk_ts,
    public_channel,
)


def reset_watermark(store):
    """Tests only: the store API is deliberately monotonic (R18)."""
    store.conn.execute(
        "UPDATE slack_source SET last_watermark = '' WHERE source_id = ?",
        (SOURCE_ID,),
    )
    store.conn.commit()


# ── sync ──────────────────────────────────────────────────────────────

def test_full_sync_ingests_every_message(registered_store, fixture_data):
    """T-SY-1."""
    engine = make_engine(registered_store, fixture_data)
    result = engine.sync(SOURCE_ID)

    assert result.ingested == 12
    assert result.total == 12
    assert result.unresolved_count == 0
    assert result.watermark == mk_ts(11)
    assert len(registered_store.list_messages(SOURCE_ID, limit=100)) == 12


def test_threads_are_normalized_from_thread_ts(registered_store, fixture_data):
    """R7: three roots, each with three replies, root included."""
    make_engine(registered_store, fixture_data).sync(SOURCE_ID)

    for root in (0, 4, 8):
        thread = registered_store.list_messages(SOURCE_ID, thread_ts=mk_ts(root))
        assert [m.ts for m in thread] == [mk_ts(root + i) for i in range(4)]
        assert thread[0].message_key == message_key_for_source(SOURCE_ID, mk_ts(root))


def test_resync_fetches_nothing_new(registered_store, fixture_data):
    """T-SY-2: the checkpoint makes a repeat run free, and idempotent."""
    engine = make_engine(registered_store, fixture_data)
    engine.sync(SOURCE_ID)
    again = engine.sync(SOURCE_ID)

    assert again.total == 0
    assert again.watermark == mk_ts(11)
    assert len(registered_store.list_messages(SOURCE_ID, limit=100)) == 12


def test_replaying_the_whole_window_is_a_noop(registered_store, fixture_data):
    """T-SY-2 (idempotent retry): re-reading old messages duplicates nothing."""
    engine = make_engine(registered_store, fixture_data)
    engine.sync(SOURCE_ID)
    reset_watermark(registered_store)

    replay = engine.sync(SOURCE_ID)
    assert replay.noop == 12
    assert replay.ingested == 0
    assert replay.updated == 0
    assert replay.watermark == mk_ts(11)
    assert len(registered_store.list_messages(SOURCE_ID, limit=100)) == 12


def test_sync_never_tombstones(registered_store, fixture_data):
    """T-SY-4 / R22: history does not report deletions, so neither do we."""
    engine = make_engine(registered_store, fixture_data)
    engine.sync(SOURCE_ID)

    del fixture_data["channels"]["C0FIXTURE1"]["messages"][5]
    reset_watermark(registered_store)
    result = make_engine(registered_store, fixture_data).sync(SOURCE_ID)

    assert result.tombstoned == 0
    assert len(registered_store.list_messages(SOURCE_ID, limit=100)) == 12


def test_quarantined_channel_stores_no_messages(registered_store):
    """T-SY-7: a denied ACL means nothing is written at all."""
    fixture = build_fixture(info=public_channel(is_private=True))
    result = make_engine(registered_store, fixture).sync(SOURCE_ID)

    assert result.quarantined == 1
    assert result.ingested == 0
    assert registered_store.list_messages(SOURCE_ID, limit=100) == []
    assert registered_store.conn.execute(
        "SELECT COUNT(*) FROM slack_message"
    ).fetchone()[0] == 0


def test_quarantined_source_is_not_re_entered(registered_store):
    """R4: no automatic retry after quarantine."""
    fixture = build_fixture(info=public_channel(is_private=True))
    engine = make_engine(registered_store, fixture)
    engine.sync(SOURCE_ID)

    second = engine.sync(SOURCE_ID)
    assert "deny:source_quarantined" in second.errors
    assert second.ingested == 0


def test_revoked_source_is_denied(registered_store, fixture_data):
    registered_store.revoke_source(SOURCE_ID, "out of scope")
    result = make_engine(registered_store, fixture_data).sync(SOURCE_ID)
    assert "deny:source_revoked" in result.errors
    assert result.ingested == 0


def test_unknown_source_is_refused(store, fixture_data):
    with pytest.raises(SlackStoreError) as exc:
        make_engine(store, fixture_data).sync("slack:T0FIXTURE:C0MISSING")
    assert exc.value.code == "deny:source_unregistered"


# ── watermark safety ──────────────────────────────────────────────────

def test_watermark_stops_before_an_unresolved_message(registered_store, fixture_data):
    """T-SY-6 (core): a rejected item is retried, never skipped."""
    engine = make_engine(registered_store, fixture_data)
    engine.sync(SOURCE_ID)

    blocker = message_key_for_source(SOURCE_ID, mk_ts(5))
    registered_store.tombstone_message(blocker, "reconcile:remote_absent")
    reset_watermark(registered_store)

    result = engine.sync(SOURCE_ID)

    assert result.rejected == 1
    assert any("reject:tombstoned_source" in e for e in result.errors)
    assert result.watermark == mk_ts(4)
    assert result.watermark < mk_ts(5)


def test_unorderable_message_holds_the_checkpoint_entirely(registered_store):
    """An invalid ts has no position, so nothing may be committed past it."""
    messages = [
        {"ts": mk_ts(0), "user": "U1", "text": "ok"},
        {"ts": "not-a-timestamp", "user": "U1", "text": "bad"},
        {"ts": mk_ts(2), "user": "U1", "text": "ok too"},
    ]
    fixture = build_fixture(messages=messages)
    result = make_engine(registered_store, fixture).sync(SOURCE_ID)

    assert result.rejected == 1
    assert result.watermark == ""
    assert registered_store.get_source(SOURCE_ID).last_watermark == ""


def test_recorded_errors_never_carry_message_bodies(registered_store):
    """R37: failure state holds identifiers and codes, not content."""
    messages = [
        {"ts": mk_ts(0), "user": "U1", "text": "ok"},
        {"ts": "not-a-timestamp", "user": "U1", "text": "TOP SECRET BODY"},
    ]
    fixture = build_fixture(messages=messages)
    result = make_engine(registered_store, fixture).sync(SOURCE_ID)

    assert result.rejected == 1
    stored_error = registered_store.get_source(SOURCE_ID).last_error
    assert "TOP SECRET BODY" not in stored_error
    assert "TOP SECRET BODY" not in " ".join(result.errors)
    assert "reject:invalid_ts" in stored_error


@pytest.mark.parametrize(
    "committed,unresolved,previous,expected",
    [
        ([mk_ts(1), mk_ts(2)], [], "", mk_ts(2)),
        ([mk_ts(1), mk_ts(3)], [mk_ts(2)], "", mk_ts(1)),
        ([], [mk_ts(0)], mk_ts(5), mk_ts(5)),
        ([mk_ts(1)], [], mk_ts(9), mk_ts(9)),
        ([], [], "", ""),
    ],
)
def test_safe_watermark_rules(committed, unresolved, previous, expected):
    """T-SY-9 / R18: never past a blocker, never backwards."""
    assert safe_watermark(committed, unresolved, previous) == expected


# ── reconcile ─────────────────────────────────────────────────────────

def test_reconcile_tombstones_a_remotely_deleted_message(
    registered_store, fixture_data
):
    """T-SY-5."""
    engine = make_engine(registered_store, fixture_data)
    engine.sync(SOURCE_ID)

    removed_ts = fixture_data["channels"]["C0FIXTURE1"]["messages"].pop(5)["ts"]
    result = make_engine(registered_store, fixture_data).reconcile(
        SOURCE_ID, since=mk_ts(0)
    )

    assert result.tombstoned == 1
    stored = registered_store.get_message(
        message_key_for_source(SOURCE_ID, removed_ts)
    )
    assert stored.tombstoned is True
    assert stored.tombstone_reason == RECONCILE_REMOTE_ABSENT
    assert stored.text  # body retained
    assert len(registered_store.list_messages(SOURCE_ID, limit=100)) == 11


def test_reconcile_detects_an_edit(registered_store, fixture_data):
    """T-SY-3 / R21: hash change bumps the version."""
    engine = make_engine(registered_store, fixture_data)
    engine.sync(SOURCE_ID)

    fixture_data["channels"]["C0FIXTURE1"]["messages"][3]["text"] = "edited body"
    fixture_data["channels"]["C0FIXTURE1"]["messages"][3]["edited_ts"] = mk_ts(20)
    result = make_engine(registered_store, fixture_data).reconcile(
        SOURCE_ID, since=mk_ts(0)
    )

    assert result.updated == 1
    assert result.tombstoned == 0
    edited = registered_store.get_message(
        message_key_for_source(SOURCE_ID, mk_ts(3))
    )
    assert edited.text == "edited body"
    assert edited.version == 2
    assert edited.edited_ts == mk_ts(20)


def test_reconcile_is_idempotent(registered_store, fixture_data):
    engine = make_engine(registered_store, fixture_data)
    engine.sync(SOURCE_ID)

    first = make_engine(registered_store, fixture_data).reconcile(
        SOURCE_ID, since=mk_ts(0)
    )
    second = make_engine(registered_store, fixture_data).reconcile(
        SOURCE_ID, since=mk_ts(0)
    )
    assert first.noop == second.noop == 12
    assert first.tombstoned == second.tombstoned == 0


def test_reconcile_window_is_bounded(registered_store, fixture_data):
    """R23: only the requested window is diffed."""
    engine = make_engine(registered_store, fixture_data)
    engine.sync(SOURCE_ID)

    fixture_data["channels"]["C0FIXTURE1"]["messages"].pop(0)  # ts mk_ts(0)
    result = make_engine(registered_store, fixture_data).reconcile(
        SOURCE_ID, since=mk_ts(4)
    )

    assert result.tombstoned == 0
    assert registered_store.get_message(
        message_key_for_source(SOURCE_ID, mk_ts(0))
    ).tombstoned is False


def test_reconcile_requires_a_valid_since(registered_store, fixture_data):
    engine = make_engine(registered_store, fixture_data)
    with pytest.raises(SlackStoreError) as exc:
        engine.reconcile(SOURCE_ID, since="")
    assert exc.value.code == "reject:invalid_ts"


def test_partial_remote_failure_tombstones_nothing(registered_store, fixture_data):
    """T-SY-8 / R24: a truncated response is not evidence of deletion."""
    engine = make_engine(registered_store, fixture_data)
    engine.sync(SOURCE_ID)
    before = registered_store.get_source(SOURCE_ID).last_watermark

    failing = make_engine(registered_store, fixture_data, raise_after=3)
    result = failing.reconcile(SOURCE_ID, since=mk_ts(0))

    assert result.tombstoned == 0
    assert result.failed == 1
    assert result.watermark == before
    assert len(registered_store.list_messages(SOURCE_ID, limit=100)) == 12


def test_reconcile_respects_the_acl_gate(registered_store):
    """A denied channel is not reconciled, and is not fetched from."""
    fixture = build_fixture(info=public_channel(is_ext_shared=True))
    engine = make_engine(registered_store, fixture)
    result = engine.reconcile(SOURCE_ID, since=mk_ts(0))

    assert result.quarantined == 1
    assert not any(c.startswith("history") for c in engine.connector.calls)

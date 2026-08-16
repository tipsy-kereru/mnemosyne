"""Contract §2 / §5.1 — lifecycle, idempotent upsert/delete, checkpoint."""

from __future__ import annotations

import pytest

from mnemosyne.integrations.slack.acl import ChannelInfo, utc_now_iso
from mnemosyne.integrations.slack.identity import message_hash, message_key_for_source
from mnemosyne.integrations.slack.schema import init_slack_schema
from mnemosyne.integrations.slack.store import (
    NOT_FOUND,
    SOURCE_ACL_VERIFIED,
    SOURCE_ACTIVE,
    SOURCE_QUARANTINED,
    SOURCE_REGISTERED,
    SOURCE_REVOKED,
    SOURCE_STALE,
    TOMBSTONED,
    TOMBSTONED_NOOP,
    UPSERT_INSERTED,
    UPSERT_NOOP,
    UPSERT_UPDATED,
    SlackMessage,
    SlackStore,
    SlackStoreError,
)

from .conftest import CHANNEL_ID, SCOPE_ID, SOURCE_ID, TEAM_ID, mk_ts


def make_message(source_id=SOURCE_ID, offset=0, text="hello", **overrides):
    ts = overrides.pop("ts", mk_ts(offset))
    return SlackMessage(
        message_key=message_key_for_source(source_id, ts),
        source_id=source_id,
        thread_ts=overrides.pop("thread_ts", ts),
        ts=ts,
        content_hash=message_hash(text),
        text=text,
        **overrides,
    )


def channel_info(**overrides):
    base = dict(channel_id=CHANNEL_ID, members=["U1"], captured_at=utc_now_iso())
    base.update(overrides)
    return ChannelInfo(**base)


# ── Schema ────────────────────────────────────────────────────────────

def test_schema_init_is_idempotent(db_path):
    """T-ST-5."""
    store = SlackStore(db_path)
    init_slack_schema(store.conn)
    init_slack_schema(store.conn)
    tables = {
        row[0]
        for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'slack_%'"
        )
    }
    assert tables == {"slack_source", "slack_message", "slack_quarantine"}
    store.close()


# ── Lifecycle ─────────────────────────────────────────────────────────

def test_register_starts_in_registered(store):
    source = store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID)
    assert source.source_id == SOURCE_ID
    assert source.status == SOURCE_REGISTERED
    assert source.last_watermark == ""


def test_register_requires_a_scope(store):
    with pytest.raises(SlackStoreError) as exc:
        store.register_source(TEAM_ID, CHANNEL_ID, "")
    assert exc.value.code == "deny:scope_mismatch"


def test_unsupported_acl_mode_is_refused(store):
    with pytest.raises(SlackStoreError):
        store.register_source(TEAM_ID, CHANNEL_ID, SCOPE_ID, acl_mode="open")


def test_record_acl_promotes_registered_to_acl_verified(registered_store):
    source = registered_store.record_acl(SOURCE_ID, channel_info())
    assert source.status == SOURCE_ACL_VERIFIED
    assert source.acl_users == ["U1"]
    assert source.channel_type == "public_channel"


@pytest.mark.parametrize(
    "start,target,allowed",
    [
        (SOURCE_REGISTERED, SOURCE_ACL_VERIFIED, True),
        (SOURCE_REGISTERED, SOURCE_ACTIVE, False),
        (SOURCE_ACL_VERIFIED, SOURCE_ACTIVE, True),
        (SOURCE_ACTIVE, SOURCE_STALE, True),
        (SOURCE_STALE, SOURCE_ACL_VERIFIED, True),
        (SOURCE_QUARANTINED, SOURCE_ACTIVE, False),
        (SOURCE_QUARANTINED, SOURCE_REGISTERED, True),
        (SOURCE_REVOKED, SOURCE_ACTIVE, False),
        (SOURCE_REVOKED, SOURCE_ACL_VERIFIED, False),
    ],
)
def test_lifecycle_transitions(registered_store, start, target, allowed):
    """T-ST-1 / R5: illegal transitions are refused, not silently applied."""
    registered_store.conn.execute(
        "UPDATE slack_source SET status = ? WHERE source_id = ?", (start, SOURCE_ID)
    )
    registered_store.conn.commit()

    if allowed:
        assert registered_store.set_status(SOURCE_ID, target).status == target
    else:
        with pytest.raises(SlackStoreError) as exc:
            registered_store.set_status(SOURCE_ID, target)
        assert exc.value.code == "deny:invalid_transition"
        assert registered_store.get_source(SOURCE_ID).status == start


def test_revoke_is_terminal_and_keeps_messages(registered_store):
    """R3: revoking hides a source; it does not destroy evidence."""
    registered_store.upsert_message(make_message())
    assert registered_store.revoke_source(SOURCE_ID, "no longer in scope") is True
    assert registered_store.revoke_source(SOURCE_ID, "again") is False

    source = registered_store.get_source(SOURCE_ID)
    assert source.status == SOURCE_REVOKED
    assert source.revoked_at
    assert len(registered_store.list_messages(SOURCE_ID)) == 1


def test_revoked_source_is_not_searchable(registered_store):
    registered_store.upsert_message(make_message(text="findable"))
    assert registered_store.search_messages(None, "findable")
    registered_store.revoke_source(SOURCE_ID, "revoked")
    assert registered_store.search_messages(None, "findable") == []


# ── Upsert / tombstone idempotency ────────────────────────────────────

def test_upsert_insert_noop_update_sequence(registered_store):
    """T-ST-2: retrying an unchanged message is a no-op, an edit is not."""
    assert registered_store.upsert_message(make_message()) == UPSERT_INSERTED
    assert registered_store.upsert_message(make_message()) == UPSERT_NOOP
    assert registered_store.upsert_message(
        make_message(text="edited")
    ) == UPSERT_UPDATED

    stored = registered_store.get_message(message_key_for_source(SOURCE_ID, mk_ts(0)))
    assert stored.version == 2
    assert stored.text == "edited"
    assert stored.first_seen_at <= stored.updated_at


def test_edited_ts_alone_counts_as_an_edit(registered_store):
    """R21: the (b) branch — Slack reports an edit with identical text."""
    registered_store.upsert_message(make_message())
    outcome = registered_store.upsert_message(make_message(edited_ts=mk_ts(1)))
    assert outcome == UPSERT_UPDATED


def test_tombstone_is_idempotent_and_preserves_the_body(registered_store):
    """T-ST-3 / R6."""
    registered_store.upsert_message(make_message(text="keep me"))
    key = message_key_for_source(SOURCE_ID, mk_ts(0))

    assert registered_store.tombstone_message(key, "reconcile:remote_absent") == TOMBSTONED
    assert registered_store.tombstone_message(key, "reconcile:remote_absent") == TOMBSTONED_NOOP

    stored = registered_store.get_message(key)
    assert stored.tombstoned is True
    assert stored.text == "keep me"
    assert registered_store.list_messages(SOURCE_ID) == []
    assert len(registered_store.list_messages(SOURCE_ID, include_tombstoned=True)) == 1


def test_tombstone_of_unknown_key_reports_not_found(registered_store):
    assert registered_store.tombstone_message("slack:T:C:1712345678.000100", "x") == NOT_FOUND


def test_tombstoned_message_is_not_resurrected(registered_store):
    """T-ST-4 / R6."""
    registered_store.upsert_message(make_message())
    key = message_key_for_source(SOURCE_ID, mk_ts(0))
    registered_store.tombstone_message(key, "reconcile:remote_absent")

    with pytest.raises(SlackStoreError) as exc:
        registered_store.upsert_message(make_message(text="back from the dead"))
    assert exc.value.code == "reject:tombstoned_source"


def test_upsert_rejects_invalid_timestamps(registered_store):
    msg = make_message()
    msg.ts = "nope"
    with pytest.raises(SlackStoreError) as exc:
        registered_store.upsert_message(msg)
    assert exc.value.code == "reject:invalid_ts"


def test_upsert_rejects_a_key_that_does_not_match_its_ts(registered_store):
    """R11: the key must be recomputable from source_id and ts."""
    msg = make_message()
    msg.message_key = message_key_for_source(SOURCE_ID, mk_ts(9))
    with pytest.raises(SlackStoreError) as exc:
        registered_store.upsert_message(msg)
    assert exc.value.code == "reject:identity_mismatch"


# ── Threads ───────────────────────────────────────────────────────────

def test_list_messages_by_thread_is_ordered(registered_store):
    root = mk_ts(0)
    for offset in (0, 2, 1):
        registered_store.upsert_message(
            make_message(offset=offset, thread_ts=root, text=f"m{offset}")
        )
    registered_store.upsert_message(make_message(offset=5, text="other thread"))

    thread = registered_store.list_messages(SOURCE_ID, thread_ts=root)
    assert [m.ts for m in thread] == [mk_ts(0), mk_ts(1), mk_ts(2)]


# ── Checkpoint ────────────────────────────────────────────────────────

def test_checkpoint_never_moves_backwards(registered_store):
    """R18 monotonicity, enforced at the write."""
    registered_store.save_checkpoint(SOURCE_ID, mk_ts(5), 5)
    registered_store.save_checkpoint(SOURCE_ID, mk_ts(2), 7)
    assert registered_store.get_source(SOURCE_ID).last_watermark == mk_ts(5)


def test_checkpoint_rejects_an_invalid_watermark(registered_store):
    with pytest.raises(SlackStoreError) as exc:
        registered_store.save_checkpoint(SOURCE_ID, "garbage", 1)
    assert exc.value.code == "reject:invalid_ts"


def test_record_error_leaves_the_watermark_alone(registered_store):
    """R20."""
    registered_store.save_checkpoint(SOURCE_ID, mk_ts(3), 3)
    registered_store.record_error(SOURCE_ID, "boom")
    source = registered_store.get_source(SOURCE_ID)
    assert source.last_watermark == mk_ts(3)
    assert source.last_error == "boom"


def test_record_error_redacts_tokens(registered_store):
    """T-ST-7 / R29: a token must not survive in the database."""
    registered_store.record_error(SOURCE_ID, "auth failed for xoxb-123-ABCdef")
    stored = registered_store.get_source(SOURCE_ID).last_error
    assert "xoxb-123-ABCdef" not in stored
    assert "REDACTED" in stored


# ── Quarantine resolution ─────────────────────────────────────────────

def test_replayed_resolution_returns_source_to_registered(registered_store):
    registered_store.quarantine(SOURCE_ID, SOURCE_ID, "quarantine:deny:acl_stale", {})
    assert registered_store.get_source(SOURCE_ID).status == SOURCE_QUARANTINED

    assert registered_store.resolve_quarantine(
        SOURCE_ID, SOURCE_ID, actor="alice", resolution="replayed", reason="acl refreshed"
    ) is True
    assert registered_store.get_source(SOURCE_ID).status == SOURCE_REGISTERED
    assert registered_store.list_quarantine() == []


def test_rejected_resolution_leaves_the_source_quarantined(registered_store):
    registered_store.quarantine(SOURCE_ID, SOURCE_ID, "quarantine:deny:channel_type", {})
    registered_store.resolve_quarantine(
        SOURCE_ID, SOURCE_ID, actor="alice", resolution="rejected", reason="private"
    )
    assert registered_store.get_source(SOURCE_ID).status == SOURCE_QUARANTINED


def test_resolution_requires_an_actor_and_a_known_resolution(registered_store):
    registered_store.quarantine(SOURCE_ID, SOURCE_ID, "quarantine:x", {})
    with pytest.raises(SlackStoreError):
        registered_store.resolve_quarantine(
            SOURCE_ID, SOURCE_ID, actor="", resolution="replayed", reason="r"
        )
    with pytest.raises(SlackStoreError):
        registered_store.resolve_quarantine(
            SOURCE_ID, SOURCE_ID, actor="alice", resolution="maybe", reason="r"
        )
    assert registered_store.get_source(SOURCE_ID).status == SOURCE_QUARANTINED


def test_resolving_twice_reports_no_change(registered_store):
    registered_store.quarantine(SOURCE_ID, SOURCE_ID, "quarantine:x", {})
    assert registered_store.resolve_quarantine(
        SOURCE_ID, SOURCE_ID, actor="a", resolution="replayed", reason="r"
    ) is True
    assert registered_store.resolve_quarantine(
        SOURCE_ID, SOURCE_ID, actor="a", resolution="replayed", reason="r"
    ) is False


# ── Explicit destruction ──────────────────────────────────────────────

def test_purge_is_the_only_delete(registered_store):
    """T-ST-6."""
    registered_store.upsert_message(make_message())
    registered_store.quarantine(SOURCE_ID, SOURCE_ID, "quarantine:x", {})

    removed = registered_store.purge_source(SOURCE_ID)
    assert removed >= 3
    assert registered_store.get_source(SOURCE_ID) is None
    assert registered_store.conn.execute(
        "SELECT COUNT(*) FROM slack_message"
    ).fetchone()[0] == 0

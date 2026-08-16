"""Contract §3 — stable identity (T-ID-1..5)."""

from __future__ import annotations

import pytest

from mnemosyne.integrations.slack.identity import (
    SlackIdentityError,
    is_valid_ts,
    message_hash,
    message_key,
    message_key_for_source,
    parse_source_id,
    require_ts,
    source_id,
    thread_key,
)

from .conftest import CHANNEL_ID, TEAM_ID, mk_ts


def test_id_shapes_are_deterministic():
    """T-ID-1: identical input always yields the identical identifier."""
    ts = mk_ts(0)
    assert source_id(TEAM_ID, CHANNEL_ID) == f"slack:{TEAM_ID}:{CHANNEL_ID}"
    assert message_key(TEAM_ID, CHANNEL_ID, ts) == f"slack:{TEAM_ID}:{CHANNEL_ID}:{ts}"
    assert message_key(TEAM_ID, CHANNEL_ID, ts) == message_key(
        TEAM_ID, CHANNEL_ID, ts
    )


def test_thread_root_key_equals_message_key():
    """R7: a root message threads onto itself."""
    ts = mk_ts(0)
    assert thread_key(TEAM_ID, CHANNEL_ID, ts) == message_key(TEAM_ID, CHANNEL_ID, ts)


def test_source_id_round_trip():
    """T-ID-2."""
    assert parse_source_id(source_id(TEAM_ID, CHANNEL_ID)) == (TEAM_ID, CHANNEL_ID)


@pytest.mark.parametrize(
    "bad",
    ["", "slack:T1", "slack:T1:C1:extra", "notslack:T1:C1", "slack::C1"],
)
def test_malformed_source_id_is_rejected(bad):
    with pytest.raises(SlackIdentityError) as exc:
        parse_source_id(bad)
    assert exc.value.code == "reject:identity_mismatch"


@pytest.mark.parametrize(
    "bad", ["abc", "1712345678", "1712345678.0001", "171234567.000100", "", "1712345678.0001000"]
)
def test_invalid_ts_rejected(bad):
    """T-ID-3 / R8."""
    assert is_valid_ts(bad) is False
    with pytest.raises(SlackIdentityError) as exc:
        require_ts(bad)
    assert exc.value.code == "reject:invalid_ts"


def test_valid_ts_accepted():
    assert is_valid_ts(mk_ts(0)) is True


def test_validated_ts_sorts_lexicographically_like_numbers():
    """T-ID-4 / R9: fixed width is what makes string order correct."""
    stamps = [mk_ts(n, micro=m) for n, m in ((5, 1), (0, 999999), (12, 0), (0, 1))]
    assert all(is_valid_ts(s) for s in stamps)
    assert sorted(stamps) == sorted(stamps, key=float)

    # The equivalence is a consequence of validation, not of ts strings in
    # general: a short (invalid) stamp breaks it.
    mixed = stamps + ["999999999.000001"]
    assert not is_valid_ts("999999999.000001")
    assert sorted(mixed) != sorted(mixed, key=float)


def test_message_hash_is_stable_and_sensitive():
    """T-ID-5 / R10: the no-op decision rests on this."""
    assert message_hash("hello") == message_hash("hello")
    assert message_hash("hello") != message_hash("hellp")
    assert message_hash("").startswith("sha256:")


def test_message_key_for_source_matches_direct_construction():
    ts = mk_ts(3)
    assert message_key_for_source(
        source_id(TEAM_ID, CHANNEL_ID), ts
    ) == message_key(TEAM_ID, CHANNEL_ID, ts)


def test_message_key_rejects_invalid_ts():
    with pytest.raises(SlackIdentityError) as exc:
        message_key(TEAM_ID, CHANNEL_ID, "nope")
    assert exc.value.code == "reject:invalid_ts"

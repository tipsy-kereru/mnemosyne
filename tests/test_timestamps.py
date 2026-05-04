"""Tests for project timestamp helpers."""

from datetime import datetime, timezone

from mnemosyne.timestamps import utc_now_iso


def test_utc_now_iso_preserves_naive_utc_shape() -> None:
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    value = utc_now_iso()
    after = datetime.now(timezone.utc).replace(tzinfo=None)

    parsed = datetime.fromisoformat(value)

    assert parsed.tzinfo is None
    assert before <= parsed <= after
    assert not value.endswith("Z")
    assert "+" not in value

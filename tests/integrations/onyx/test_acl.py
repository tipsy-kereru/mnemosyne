"""ACL snapshot and quarantine policy tests.

Implements §8 권한 테스트:
- ACL snapshot freshness / staleness detection
- Quarantine on missing ACL (§3 rule 7)
- Quarantine on missing connector mapping
- Fresh ACL passes through
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mnemosyne.integrations.onyx.acl import (
    DEFAULT_ACL_TTL_HOURS,
    QuarantineRecord,
    create_quarantine,
    is_acl_fresh,
    should_quarantine,
)
from mnemosyne.integrations.onyx.contract import AccessSnapshot, Envelope
from mnemosyne.integrations.onyx.config import ConnectorMapping


def _fresh_snapshot() -> AccessSnapshot:
    return AccessSnapshot(
        users=["alice@example.com"],
        groups=["project-client-a"],
        captured_at=datetime.now(timezone.utc).isoformat(),
    )


def _envelope(snapshot: AccessSnapshot | None = None) -> Envelope:
    return Envelope(
        source_system="onyx",
        onyx_connector_id="connector-17",
        external_document_id="github:test:issue:1",
        title="Test doc",
        sections=[{"text": "content"}],
        scope_id="client-a",
        source_channel="github",
        access_snapshot=snapshot or AccessSnapshot(),
    )


def _mapping(acl_mode: str = "require_snapshot") -> ConnectorMapping:
    return ConnectorMapping(
        connector_id="connector-17",
        scope_id="client-a",
        source_channel="github",
        acl_mode=acl_mode,
    )


class TestACLFreshness:
    def test_fresh_snapshot_is_fresh(self):
        snap = _fresh_snapshot()
        assert is_acl_fresh(snap) is True

    def test_empty_snapshot_is_stale(self):
        assert is_acl_fresh(AccessSnapshot()) is False

    def test_snapshot_without_timestamp_is_stale(self):
        snap = AccessSnapshot(users=["a"], captured_at=None)
        assert is_acl_fresh(snap) is False

    def test_expired_snapshot_is_stale(self):
        old = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_ACL_TTL_HOURS + 1)
        snap = AccessSnapshot(
            users=["a"], captured_at=old.isoformat()
        )
        assert is_acl_fresh(snap) is False

    def test_malformed_timestamp_is_stale(self):
        snap = AccessSnapshot(users=["a"], captured_at="not-a-date")
        assert is_acl_fresh(snap) is False


class TestQuarantineDecision:
    def test_no_mapping_quarantines(self):
        """§4: Fingerprinted → Quarantined when mapping missing."""
        env = _envelope(_fresh_snapshot())
        quarantined, reason = should_quarantine(env, mapping=None)
        assert quarantined is True
        assert "mapping" in reason

    def test_empty_acl_quarantines(self):
        """§3 rule 7: ACL-unverifiable documents quarantined."""
        env = _envelope(AccessSnapshot())
        quarantined, reason = should_quarantine(env, _mapping())
        assert quarantined is True
        assert "empty" in reason

    def test_stale_acl_quarantines(self):
        old = datetime.now(timezone.utc) - timedelta(hours=50)
        env = _envelope(
            AccessSnapshot(users=["a"], captured_at=old.isoformat())
        )
        quarantined, reason = should_quarantine(env, _mapping())
        assert quarantined is True
        assert "stale" in reason

    def test_fresh_acl_passes(self):
        env = _envelope(_fresh_snapshot())
        quarantined, reason = should_quarantine(env, _mapping())
        assert quarantined is False

    def test_open_mode_never_quarantines(self):
        env = _envelope(AccessSnapshot())
        quarantined, _ = should_quarantine(env, _mapping("open"))
        assert quarantined is False

    def test_owner_only_mode_without_owner_quarantines(self):
        env = _envelope(AccessSnapshot())
        quarantined, reason = should_quarantine(env, _mapping("owner_only"))
        assert quarantined is True
        assert reason == "quarantine:owner_unidentified"


class TestQuarantineRecord:
    def test_create_quarantine_captures_metadata(self):
        env = _envelope(_fresh_snapshot())
        rec = create_quarantine(env, "test reason")
        assert rec.source_doc_id == env.source_doc_id
        assert rec.scope_id == "client-a"
        assert rec.reason == "test reason"
        assert rec.resolved is False
        assert rec.quarantined_at  # auto-filled

    def test_quarantine_snapshot_has_provenance(self):
        env = _envelope(_fresh_snapshot())
        rec = create_quarantine(env, "test")
        assert rec.envelope_snapshot["title"] == env.title
        assert rec.envelope_snapshot["external_uri"] == env.external_uri



def test_t56_owner_only_without_owner_is_quarantined():
    env = _envelope(_fresh_snapshot())
    env.owner_id = ""
    quarantined, reason = should_quarantine(env, _mapping("owner_only"))
    assert quarantined is True
    assert reason == "quarantine:owner_unidentified"


def test_t57_scope_mismatch_precedes_open_mode():
    env = _envelope(_fresh_snapshot())
    env.scope_id = "scope-other"
    quarantined, reason = should_quarantine(env, _mapping("open"))
    assert quarantined is True
    assert reason == "quarantine:scope_mismatch"
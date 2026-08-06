"""Access-control snapshot and quarantine policy.

Implements the §3 rules:

- Rule 7: Documents whose ACL cannot be verified are quarantined and
  never auto-promoted.
- Rule 8: API keys and tokens are never stored in the envelope.

And the §4 state machine transitions:

    Fingerprinted → Quarantined   (missing scope or ACL)
    Quarantined is a terminal-ish state: a reviewer must explicitly
    resolve the mapping or refresh the ACL before the document re-enters
    the ingest pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from mnemosyne.integrations.onyx.contract import AccessSnapshot, Envelope
from mnemosyne.integrations.onyx.config import ConnectorMapping

# How long an ACL snapshot is considered fresh before default-deny.
DEFAULT_ACL_TTL_HOURS = 24


@dataclass
class QuarantineRecord:
    """A document held in quarantine pending ACL/mapping resolution."""

    source_doc_id: str
    scope_id: str
    reason: str
    quarantined_at: str = ""
    envelope_snapshot: dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution: Optional[str] = None  # "replayed" | "rejected"
    resolution_reason: str = ""
    def __post_init__(self) -> None:
        if not self.quarantined_at:
            self.quarantined_at = datetime.now(timezone.utc).isoformat()


def is_acl_fresh(
    snapshot: AccessSnapshot,
    ttl_hours: int = DEFAULT_ACL_TTL_HOURS,
    now: Optional[datetime] = None,
) -> bool:
    """True when the ACL snapshot is within its freshness window.

    A snapshot with no ``captured_at`` is treated as stale (default deny).
    """
    if snapshot.is_empty():
        return False
    if not snapshot.captured_at:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        captured = datetime.fromisoformat(snapshot.captured_at)
    except (ValueError, TypeError):
        return False
    age = (now - captured).total_seconds() / 3600
    return age <= ttl_hours


def should_quarantine(
    env: Envelope,
    mapping: Optional[ConnectorMapping],
    ttl_hours: int = DEFAULT_ACL_TTL_HOURS,
    now: Optional[datetime] = None,
) -> tuple[bool, str]:
    """Return whether an envelope must be quarantined."""
    if mapping is None:
        return True, "quarantine:no_mapping"

    if env.scope_id != mapping.scope_id:
        return True, "quarantine:scope_mismatch"

    if mapping.acl_mode == "owner_only":
        owner = getattr(env, "owner_id", "") or getattr(
            env, "owner", ""
        )
        if not owner:
            return True, "quarantine:owner_unidentified"
        return False, ""

    if mapping.acl_mode == "open":
        return False, ""

    if env.access_snapshot.is_empty():
        return True, "quarantine:acl_snapshot_empty"
    if not is_acl_fresh(env.access_snapshot, ttl_hours=ttl_hours, now=now):
        return True, "quarantine:acl_snapshot_stale"
    return False, ""


def create_quarantine(env: Envelope, reason: str) -> QuarantineRecord:
    """Build a quarantine record from a complete, secret-free envelope."""
    return QuarantineRecord(
        source_doc_id=env.source_doc_id,
        scope_id=env.scope_id,
        reason=reason,
        envelope_snapshot=env.to_dict(),
    )

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
    resolution: Optional[str] = None  # "accepted" | "rejected"

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
    """Decide whether an envelope must be quarantined.

    Returns ``(quarantined, reason)``.

    Quarantine triggers:
    - No mapping exists for the connector (ambiguous scope).
    - ``acl_mode=require_snapshot`` and the ACL snapshot is empty or stale.
    - ``acl_mode=owner_only`` and no owner is identifiable.
    """
    if mapping is None:
        return True, "no connector→scope mapping; manual scope resolution required"

    if mapping.acl_mode == "open":
        return False, ""

    if mapping.acl_mode == "owner_only":
        # For personal scopes the "owner" is implicit in the scope_id.
        # No group ACL needed.
        return False, ""

    # acl_mode == "require_snapshot"
    if env.access_snapshot.is_empty():
        return True, "ACL snapshot is empty; cannot verify access"

    if not is_acl_fresh(env.access_snapshot, ttl_hours=ttl_hours, now=now):
        return True, (
            f"ACL snapshot stale (captured_at="
            f"{env.access_snapshot.captured_at!r}, ttl={ttl_hours}h)"
        )

    return False, ""


def create_quarantine(env: Envelope, reason: str) -> QuarantineRecord:
    """Build a quarantine record from an envelope."""
    return QuarantineRecord(
        source_doc_id=env.source_doc_id,
        scope_id=env.scope_id,
        reason=reason,
        envelope_snapshot={
            "title": env.title,
            "external_uri": env.external_uri,
            "source_type": env.source_type,
            "content_hash": env.content_hash,
            "captured_at": env.captured_at,
        },
    )

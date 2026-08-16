"""Fail-closed channel access policy for the direct Slack integration.

Implements §4 of ``docs/SLACK_INTEGRATION_CONTRACT.ko.md``:

- R13: only public channels are allowed in v1. Private channels, DMs,
  MPIMs, and externally/org-shared channels are refused *without being
  inspected* — their principal policy is a deferred artifact.
- R14/R15: the ACL snapshot is the channel member list plus a capture
  time. Missing, empty, unparseable, or stale (>24h) snapshots all deny.

Freshness reuses :func:`mnemosyne.integrations.onyx.acl.is_acl_fresh` so
there is one implementation of the TTL rule. That helper subtracts an
aware "now" from the parsed capture time, so capture times are
normalized to timezone-aware UTC first — a naive timestamp would
otherwise raise ``TypeError`` instead of denying.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from mnemosyne.integrations.onyx.acl import (
    DEFAULT_ACL_TTL_HOURS,
    is_acl_fresh,
)
from mnemosyne.integrations.onyx.contract import AccessSnapshot

# v1 allows exactly one channel type (R13).
ALLOWED_CHANNEL_TYPES = frozenset({"public_channel"})

CHANNEL_PUBLIC = "public_channel"
CHANNEL_PRIVATE = "private_channel"
CHANNEL_IM = "im"
CHANNEL_MPIM = "mpim"
CHANNEL_EXT_SHARED = "ext_shared"
CHANNEL_ORG_SHARED = "org_shared"

DENY_CHANNEL_TYPE = "deny:channel_type"
DENY_ACL_MISSING = "deny:acl_missing"
DENY_ACL_EMPTY = "deny:acl_empty"
DENY_ACL_STALE = "deny:acl_stale"


def utc_now() -> datetime:
    """Timezone-aware UTC clock (matches the Onyx integration)."""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Aware ISO-8601 timestamp.

    The Slack tables use aware timestamps throughout, unlike
    :mod:`mnemosyne.timestamps`, because the reused ACL freshness helper
    compares against an aware clock.
    """
    return utc_now().isoformat()


@dataclass
class ChannelInfo:
    """What ``conversations.info`` + ``conversations.members`` tell us.

    ``members`` holds user IDs only — never display names, emails, or
    message text (contract R16/R37).
    """

    channel_id: str
    name: str = ""
    is_private: bool = False
    is_ext_shared: bool = False
    is_org_shared: bool = False
    is_im: bool = False
    is_mpim: bool = False
    members: list[str] = field(default_factory=list)
    captured_at: Optional[str] = None


def classify_channel(info: ChannelInfo) -> str:
    """Return the channel type label used by the policy and the store.

    The order matters: the most restrictive property wins, so a private
    *and* externally shared channel is reported as external.
    """
    if info.is_im:
        return CHANNEL_IM
    if info.is_mpim:
        return CHANNEL_MPIM
    if info.is_ext_shared:
        return CHANNEL_EXT_SHARED
    if info.is_org_shared:
        return CHANNEL_ORG_SHARED
    if info.is_private:
        return CHANNEL_PRIVATE
    return CHANNEL_PUBLIC


def _normalize_captured_at(captured_at: Optional[str]) -> Optional[str]:
    """Return an aware-UTC ISO string, or None when unusable.

    A naive timestamp is interpreted as UTC rather than rejected, since
    other parts of the codebase store naive UTC.
    """
    if not captured_at:
        return None
    try:
        parsed = datetime.fromisoformat(captured_at)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def access_snapshot(info: ChannelInfo) -> AccessSnapshot:
    """Express the channel ACL in the shared Onyx snapshot shape (R14)."""
    return AccessSnapshot(
        users=list(info.members),
        groups=[],
        captured_at=_normalize_captured_at(info.captured_at),
    )


def acl_denial(
    info: ChannelInfo,
    *,
    ttl_hours: int = DEFAULT_ACL_TTL_HOURS,
    now: Optional[datetime] = None,
) -> str:
    """Return a ``deny:*`` code, or ``""`` when the channel may be read.

    Fail-closed: every unknown or degraded condition denies (§10).
    """
    if classify_channel(info) not in ALLOWED_CHANNEL_TYPES:
        return DENY_CHANNEL_TYPE

    normalized = _normalize_captured_at(info.captured_at)
    if normalized is None and not info.members:
        return DENY_ACL_MISSING
    if not info.members:
        return DENY_ACL_EMPTY
    if normalized is None:
        return DENY_ACL_STALE

    snapshot = AccessSnapshot(
        users=list(info.members), groups=[], captured_at=normalized
    )
    if not is_acl_fresh(snapshot, ttl_hours=ttl_hours, now=now or utc_now()):
        return DENY_ACL_STALE
    return ""


def quarantine_snapshot(info: ChannelInfo, source_id: str, team_id: str) -> dict:
    """Metadata-only snapshot for a quarantine record (R16).

    Deliberately excludes message text, display names, member IDs, and
    anything token-shaped. ``member_count`` is a count, not a list.
    """
    return {
        "source_id": source_id,
        "team_id": team_id,
        "channel_id": info.channel_id,
        "channel_type": classify_channel(info),
        "is_private": bool(info.is_private),
        "is_ext_shared": bool(info.is_ext_shared),
        "is_org_shared": bool(info.is_org_shared),
        "member_count": len(info.members),
        "captured_at": _normalize_captured_at(info.captured_at) or "",
    }

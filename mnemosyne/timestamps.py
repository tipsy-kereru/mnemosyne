"""Timestamp helpers for project-owned UTC metadata."""

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return the current UTC time as a naive ISO-8601 string.

    Mnemosyne historically stores UTC timestamps without an explicit offset.
    Use a timezone-aware clock internally, then remove the timezone marker to
    preserve the existing storage/output shape while avoiding deprecated
    naive UTC clock APIs.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

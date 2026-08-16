"""Stable identity for Slack sources, threads, and messages.

Implements §3 of ``docs/SLACK_INTEGRATION_CONTRACT.ko.md``:

- R7: a thread is derived from ``thread_ts``; the root message satisfies
  ``thread_key == message_key``.
- R8: ``ts`` must match ``^\\d{10}\\.\\d{6}$``; anything else is
  ``reject:invalid_ts``.
- R9: because ``ts`` is fixed-width, lexicographic comparison equals
  numeric comparison — but *only* after R8 validation. Unvalidated
  timestamps must never take part in a comparison, so there is
  deliberately no sort-key helper here.
- R10: content hash reuses the Onyx normalization so identical text
  yields an identical hash (the basis of the ``noop`` decision).
"""

from __future__ import annotations

import re

from mnemosyne.integrations.onyx.contract import compute_content_hash

# The isolated source channel for this direct integration. Distinct from
# the ``slack`` channel used by Onyx-sourced documents (contract §14).
SOURCE_CHANNEL = "work-slack"

CONTRACT_VERSION = "slack-1.0"

TS_PATTERN = re.compile(r"^\d{10}\.\d{6}$")

_ID_SEPARATOR = ":"
_ID_PREFIX = "slack"


class SlackIdentityError(ValueError):
    """Raised when an identifier violates the identity contract."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _require_component(name: str, value: str) -> str:
    """Reject empty components and components containing the separator."""
    if not value or _ID_SEPARATOR in value:
        raise SlackIdentityError(
            "reject:identity_mismatch",
            f"{name} must be non-empty and free of {_ID_SEPARATOR!r}",
        )
    return value


def is_valid_ts(value: str) -> bool:
    """True when ``value`` is a well-formed Slack timestamp (R8)."""
    return bool(TS_PATTERN.match(value or ""))


def require_ts(value: str) -> str:
    """Return ``value`` when valid, else raise ``reject:invalid_ts`` (R8)."""
    if not is_valid_ts(value):
        raise SlackIdentityError(
            "reject:invalid_ts", f"invalid Slack ts: {value!r}"
        )
    return value


def source_id(team_id: str, channel_id: str) -> str:
    """``slack:{team_id}:{channel_id}``."""
    return _ID_SEPARATOR.join((
        _ID_PREFIX,
        _require_component("team_id", team_id),
        _require_component("channel_id", channel_id),
    ))


def parse_source_id(value: str) -> tuple[str, str]:
    """Inverse of :func:`source_id`. Returns ``(team_id, channel_id)``."""
    parts = (value or "").split(_ID_SEPARATOR)
    if len(parts) != 3 or parts[0] != _ID_PREFIX or not all(parts[1:]):
        raise SlackIdentityError(
            "reject:identity_mismatch", f"malformed source_id: {value!r}"
        )
    return parts[1], parts[2]


def message_key(team_id: str, channel_id: str, ts: str) -> str:
    """``slack:{team_id}:{channel_id}:{ts}`` (R8-validated)."""
    return _ID_SEPARATOR.join((source_id(team_id, channel_id), require_ts(ts)))


def thread_key(team_id: str, channel_id: str, thread_ts: str) -> str:
    """Same shape as :func:`message_key`; equal to it for a thread root (R7)."""
    return message_key(team_id, channel_id, thread_ts)


def message_key_for_source(source_id_value: str, ts: str) -> str:
    """Build a message key from an existing ``source_id``."""
    team_id, channel_id = parse_source_id(source_id_value)
    return message_key(team_id, channel_id, ts)


def message_hash(text: str) -> str:
    """Content hash of one message body (R10)."""
    return compute_content_hash([{"text": text or ""}])

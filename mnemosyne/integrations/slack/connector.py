"""Connector protocol and the offline synthetic implementation.

Contract §8.5. The protocol is the only thing the sync engine talks to,
so the live Web API adapter (a later work package) and the fixture-driven
connector here are interchangeable.

``SyntheticConnector`` performs no I/O of any kind. It also records the
order of its calls, which is what lets the ACL-before-fetch rule (R12) be
asserted rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Optional, Protocol

from mnemosyne.integrations.slack.acl import ChannelInfo, utc_now_iso
from mnemosyne.integrations.slack.identity import is_valid_ts


@dataclass
class FetchedMessage:
    """One message as returned by a connector, before persistence."""

    ts: str
    thread_ts: str = ""
    user: str = ""
    text: str = ""
    edited_ts: Optional[str] = None
    subtype: str = ""

    def resolved_thread_ts(self) -> str:
        """A root message threads onto itself (R7)."""
        return self.thread_ts or self.ts


class SlackConnector(Protocol):
    """Read-only view of one Slack workspace."""

    def channel_info(self, channel_id: str) -> ChannelInfo:
        ...

    def history(
        self, channel_id: str, *, oldest: str = "", limit: int = 200
    ) -> Iterator[FetchedMessage]:
        """Messages with ``ts`` strictly greater than ``oldest``, ascending."""
        ...

    def replies(
        self, channel_id: str, thread_ts: str, *, oldest: str = ""
    ) -> Iterator[FetchedMessage]:
        """Replies of one thread, ascending, root included."""
        ...


class ChannelNotFound(LookupError):
    """The fixture has no such channel."""


class SyntheticConnector:
    """Fixture-driven connector. No network, no credentials.

    Fixture shape::

        {
          "team_id": "T0FIXTURE",
          "channels": {
            "C0FIXTURE1": {
              "info": {"is_private": false, "members": ["U1", "U2"]},
              "messages": [
                {"ts": "1712345678.000100", "user": "U1", "text": "hi"}
              ]
            }
          }
        }

    ``raise_after`` makes the connector fail partway through an
    enumeration, so the "never infer a deletion from a partial response"
    rule (R24) can be exercised.
    """

    def __init__(
        self,
        fixture: dict[str, Any],
        *,
        raise_after: Optional[int] = None,
    ) -> None:
        self.fixture = fixture
        self.raise_after = raise_after
        #: Call log used by tests to assert ACL-before-fetch (R12).
        self.calls: list[str] = []

    @property
    def team_id(self) -> str:
        return self.fixture.get("team_id", "")

    def _channel(self, channel_id: str) -> dict[str, Any]:
        channels = self.fixture.get("channels", {})
        if channel_id not in channels:
            raise ChannelNotFound(channel_id)
        return channels[channel_id]

    def channel_info(self, channel_id: str) -> ChannelInfo:
        self.calls.append(f"channel_info:{channel_id}")
        raw = dict(self._channel(channel_id).get("info", {}))
        return ChannelInfo(
            channel_id=channel_id,
            name=raw.get("name", ""),
            is_private=bool(raw.get("is_private", False)),
            is_ext_shared=bool(raw.get("is_ext_shared", False)),
            is_org_shared=bool(raw.get("is_org_shared", False)),
            is_im=bool(raw.get("is_im", False)),
            is_mpim=bool(raw.get("is_mpim", False)),
            members=list(raw.get("members", [])),
            captured_at=raw.get("captured_at") or utc_now_iso(),
        )

    def _messages(self, channel_id: str) -> list[FetchedMessage]:
        out = [
            FetchedMessage(
                ts=str(raw.get("ts", "")),
                thread_ts=str(raw.get("thread_ts", "") or ""),
                user=raw.get("user", ""),
                text=raw.get("text", ""),
                edited_ts=raw.get("edited_ts"),
                subtype=raw.get("subtype", ""),
            )
            for raw in self._channel(channel_id).get("messages", [])
        ]
        # Only validated timestamps may be ordered by string comparison
        # (R9); anything else keeps its fixture position and is rejected
        # downstream.
        return sorted(out, key=lambda m: (is_valid_ts(m.ts), m.ts))

    def history(
        self, channel_id: str, *, oldest: str = "", limit: int = 200
    ) -> Iterator[FetchedMessage]:
        self.calls.append(f"history:{channel_id}")
        emitted = 0
        for msg in self._messages(channel_id):
            if oldest and is_valid_ts(msg.ts) and msg.ts <= oldest:
                continue
            if emitted >= limit:
                return
            if self.raise_after is not None and emitted >= self.raise_after:
                raise RuntimeError("synthetic connector failure mid-enumeration")
            emitted += 1
            yield msg

    def replies(
        self, channel_id: str, thread_ts: str, *, oldest: str = ""
    ) -> Iterator[FetchedMessage]:
        self.calls.append(f"replies:{channel_id}:{thread_ts}")
        for msg in self._messages(channel_id):
            if msg.resolved_thread_ts() != thread_ts:
                continue
            if oldest and is_valid_ts(msg.ts) and msg.ts <= oldest:
                continue
            yield msg

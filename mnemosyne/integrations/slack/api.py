"""Slack Web API adapter — blocked against the real Slack by default.

Contract §7.4. The adapter exists so the mocked contract tests exercise
the same code path a real workspace eventually will, but it refuses to
talk to anything except a loopback address unless ``live_approved`` is
set. Nothing in this program sets it: reaching a real workspace is gated
on ``gate-real-slack``, which needs human approval, real channel IDs, and
a token model. A blocked call is the contract working, not a bug.

Uses ``urllib`` from the standard library. ``slack_sdk`` is deliberately
not a dependency — adding one is out of scope (§12 item 10), and the four
read endpoints needed here do not justify it.

Every failure path runs its message through ``redact`` before it reaches
a log, an exception, or the CLI.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator

from mnemosyne.integrations.slack.acl import ChannelInfo, utc_now_iso
from mnemosyne.integrations.slack.config import (
    SlackScopeError,
    assert_scopes_allowed,
    parse_scope_header,
)
from mnemosyne.integrations.slack.connector import FetchedMessage
from mnemosyne.integrations.slack.identity import is_valid_ts
from mnemosyne.integrations.slack.redact import redact

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://slack.com/api"
DEFAULT_TIMEOUT = 30
DEFAULT_PAGE_SIZE = 200

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

CODE_LIVE_BLOCKED = "blocked:live_not_approved"
CODE_MISSING_SCOPE_HEADER = "reject:missing_scope_header"

#: Slack error codes worth another attempt.
RETRYABLE = frozenset({"ratelimited", "internal_error", "service_unavailable"})

#: Slack error codes that mean the channel must be quarantined, not retried.
QUARANTINE_ERRORS = frozenset({
    "not_in_channel", "channel_not_found", "is_archived", "restricted_action",
})


class SlackApiError(Exception):
    """A Slack API call failed. ``code`` is the Slack error string."""

    def __init__(self, code: str, message: str = "", status: int = 0) -> None:
        self.code = code
        self.status = status
        super().__init__(redact(message or code))


class SlackLiveBlocked(SlackApiError):
    """A non-loopback call was attempted without explicit approval."""

    def __init__(self, message: str = "") -> None:
        super().__init__(CODE_LIVE_BLOCKED, message or CODE_LIVE_BLOCKED)


def is_loopback(base_url: str) -> bool:
    host = urllib.parse.urlparse(base_url).hostname or ""
    return host in LOOPBACK_HOSTS


def enforce_scope_header(header: str | None, *, loopback: bool) -> None:
    """Refuse a live response that carries no ``X-OAuth-Scopes`` header.

    Without the header there is nothing to check, so accepting the
    response would silently disable the over-permission guard (R30). A
    real Slack response always carries it; a stripping proxy or an
    unexpected response shape does not, and that must deny rather than
    pass. Loopback (the mock) is exempt so test servers stay simple.
    """
    if header is None and not loopback:
        raise SlackScopeError(
            CODE_MISSING_SCOPE_HEADER,
            "live response carried no X-OAuth-Scopes header; "
            "cannot verify the token is not over-permissioned",
        )
    assert_scopes_allowed(parse_scope_header(header))


class WebApiConnector:
    """Read-only Slack Web API client implementing ``SlackConnector``.

    Args:
        token: Bot token, resolved by the caller from the environment.
        base_url: API root. Anything non-loopback needs ``live_approved``.
        live_approved: Human approval for real-workspace traffic. There
            is no code path in this program that passes ``True``.
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = 3,
        initial_backoff: float = 0.5,
        live_approved: bool = False,
    ) -> None:
        if not token:
            raise SlackApiError("blocked:credential_missing", "token is required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.live_approved = live_approved
        #: Mirrors SyntheticConnector so call-order assertions work here too.
        self.calls: list[str] = []

    # ── Transport ─────────────────────────────────────────────────────

    def _guard_live(self) -> None:
        if not is_loopback(self.base_url) and not self.live_approved:
            raise SlackLiveBlocked(
                f"refusing to call {urllib.parse.urlparse(self.base_url).hostname} "
                f"without human approval (gate-real-slack)"
            )

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """One Web API GET, with scope enforcement and bounded retries."""
        self._guard_live()

        query = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v not in (None, "")}
        )
        url = f"{self.base_url}/{method}?{query}"
        backoff = self.initial_backoff
        last_error = "unknown_error"

        for attempt in range(1, self.max_retries + 1):
            request = urllib.request.Request(url, method="GET")
            request.add_header("Authorization", f"Bearer {self.token}")
            request.add_header("Accept", "application/json")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    # An over-permissioned token — or a response that gives
                    # no way to check — is refused before the body is used
                    # for anything.
                    enforce_scope_header(
                        resp.headers.get("X-OAuth-Scopes"),
                        loopback=is_loopback(self.base_url),
                    )
                    payload = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                status = exc.code
                if status == 429 or status >= 500:
                    last_error = f"http_{status}"
                    if attempt < self.max_retries:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                raise SlackApiError(
                    f"http_{status}", f"{method} failed with HTTP {status}", status
                ) from exc
            except urllib.error.URLError as exc:
                last_error = "network_error"
                if attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise SlackApiError(
                    "network_error", f"{method}: {redact(str(exc.reason))}"
                ) from exc
            except json.JSONDecodeError as exc:
                raise SlackApiError(
                    "invalid_response", f"{method} returned non-JSON"
                ) from exc

            if payload.get("ok"):
                return payload

            error = str(payload.get("error", "unknown_error"))
            if error in RETRYABLE and attempt < self.max_retries:
                last_error = error
                time.sleep(backoff)
                backoff *= 2
                continue
            raise SlackApiError(error, f"{method} returned {error}")

        raise SlackApiError(last_error, f"{method} exhausted {self.max_retries} attempts")

    def _paginate(
        self, method: str, params: dict[str, Any], key: str
    ) -> Iterator[Any]:
        """Follow ``response_metadata.next_cursor`` to exhaustion."""
        cursor = ""
        seen_cursors: set[str] = set()
        while True:
            page = self._call(method, {**params, "cursor": cursor})
            for item in page.get(key, []) or []:
                yield item
            cursor = (page.get("response_metadata") or {}).get("next_cursor", "")
            if not cursor:
                return
            if cursor in seen_cursors:
                # A server that repeats a cursor would loop us forever.
                raise SlackApiError("pagination_loop", f"{method} repeated a cursor")
            seen_cursors.add(cursor)

    # ── SlackConnector ────────────────────────────────────────────────

    def channel_info(self, channel_id: str) -> ChannelInfo:
        """Channel metadata plus the member list, as one ACL snapshot."""
        self.calls.append(f"channel_info:{channel_id}")
        payload = self._call("conversations.info", {"channel": channel_id})
        channel = payload.get("channel") or {}
        members = [str(m) for m in self._paginate(
            "conversations.members", {"channel": channel_id, "limit": DEFAULT_PAGE_SIZE},
            "members",
        )]
        return ChannelInfo(
            channel_id=channel_id,
            name=str(channel.get("name", "")),
            is_private=bool(channel.get("is_private", False)),
            is_ext_shared=bool(channel.get("is_ext_shared", False)),
            is_org_shared=bool(channel.get("is_org_shared", False)),
            is_im=bool(channel.get("is_im", False)),
            is_mpim=bool(channel.get("is_mpim", False)),
            members=members,
            captured_at=utc_now_iso(),
        )

    def history(
        self, channel_id: str, *, oldest: str = "", limit: int = DEFAULT_PAGE_SIZE
    ) -> Iterator[FetchedMessage]:
        self.calls.append(f"history:{channel_id}")
        yield from self._messages(
            "conversations.history",
            {"channel": channel_id, "oldest": oldest, "limit": min(limit, DEFAULT_PAGE_SIZE)},
            oldest=oldest,
            limit=limit,
        )

    def replies(
        self, channel_id: str, thread_ts: str, *, oldest: str = ""
    ) -> Iterator[FetchedMessage]:
        self.calls.append(f"replies:{channel_id}:{thread_ts}")
        yield from self._messages(
            "conversations.replies",
            {
                "channel": channel_id, "ts": thread_ts, "oldest": oldest,
                "limit": DEFAULT_PAGE_SIZE,
            },
            oldest=oldest,
            limit=DEFAULT_PAGE_SIZE,
        )

    def _messages(
        self,
        method: str,
        params: dict[str, Any],
        *,
        oldest: str,
        limit: int,
    ) -> Iterator[FetchedMessage]:
        """Normalize a message page stream into ascending FetchedMessages.

        Slack returns history newest-first and treats ``oldest`` as
        inclusive; the connector protocol promises ascending order and a
        strictly-greater bound, so both are corrected here rather than
        left for the sync engine to guess at.
        """
        collected: list[FetchedMessage] = []
        for raw in self._paginate(method, params, "messages"):
            ts = str(raw.get("ts", ""))
            if oldest and is_valid_ts(ts) and ts <= oldest:
                continue
            collected.append(
                FetchedMessage(
                    ts=ts,
                    thread_ts=str(raw.get("thread_ts", "") or ""),
                    user=str(raw.get("user", "")),
                    text=str(raw.get("text", "")),
                    edited_ts=(raw.get("edited") or {}).get("ts"),
                    subtype=str(raw.get("subtype", "")),
                )
            )
        collected.sort(key=lambda m: (is_valid_ts(m.ts), m.ts))
        yield from collected[:limit]

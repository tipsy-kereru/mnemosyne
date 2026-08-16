"""In-process mock of the four Slack Web API endpoints this package reads.

Lives in the package rather than in ``tests/`` for the same reason
``onyx/mock_server.py`` does: both the contract tests and a future
``--connector mock`` CLI run need it. It binds loopback only, so the
adapter's live guard treats it as an approved destination.

Never used against production. It serves fixture data in the same shape
as :class:`~mnemosyne.integrations.slack.connector.SyntheticConnector`,
so one fixture drives both the offline and the mocked-HTTP paths.

Configurable failures cover what the contract requires evidence for:
cursor pagination, rate-limit retry, auth failure, and the permission
errors that must quarantine rather than retry.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 5


class MockSlackServer:
    """Loopback-only stand-in for ``https://slack.com/api``.

    Args:
        fixture: Same shape SyntheticConnector accepts.
        expected_token: Anything else yields ``invalid_auth``.
        fail_first_n: Number of leading calls answered with
            ``fail_error`` before normal service resumes.
        page_size: Messages and members per page, to force pagination.
        granted_scopes: Value of the ``X-OAuth-Scopes`` response header.
        channel_error: Force a per-call Slack error (e.g. ``not_in_channel``).
    """

    def __init__(
        self,
        *,
        port: int = 0,
        host: str = "127.0.0.1",
        expected_token: str = "xoxb-test",
        fixture: Optional[dict[str, Any]] = None,
        fail_first_n: int = 0,
        fail_error: str = "ratelimited",
        page_size: int = DEFAULT_PAGE_SIZE,
        granted_scopes: str = "channels:read,channels:history,users:read",
        send_scope_header: bool = True,
        channel_error: str = "",
    ) -> None:
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("MockSlackServer binds loopback only")
        self.host = host
        self.port = port
        self.expected_token = expected_token
        self.fixture = fixture or {"team_id": "T0MOCK", "channels": {}}
        self.fail_first_n = fail_first_n
        self.fail_error = fail_error
        self.page_size = page_size
        self.granted_scopes = granted_scopes
        #: Set False to emulate a proxy that strips X-OAuth-Scopes.
        self.send_scope_header = send_scope_header
        self.channel_error = channel_error
        self.request_count = 0
        self.requests: list[str] = []
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        actual = self._server.server_address[1] if self._server else self.port
        return f"http://{self.host}:{actual}/api"

    # ── Fixture access ────────────────────────────────────────────────

    def _channel(self, channel_id: str) -> Optional[dict[str, Any]]:
        return self.fixture.get("channels", {}).get(channel_id)

    def _page(self, items: list[Any], cursor: str) -> tuple[list[Any], str]:
        """Slice ``items`` by an integer-offset cursor."""
        start = int(cursor) if cursor.isdigit() else 0
        window = items[start:start + self.page_size]
        nxt = start + self.page_size
        return window, (str(nxt) if nxt < len(items) else "")

    def _dispatch(self, method: str, params: dict[str, str]) -> dict[str, Any]:
        channel_id = params.get("channel", "")
        channel = self._channel(channel_id)
        if channel is None:
            return {"ok": False, "error": "channel_not_found"}
        if self.channel_error:
            return {"ok": False, "error": self.channel_error}

        cursor = params.get("cursor", "")
        info = dict(channel.get("info", {}))

        if method == "conversations.info":
            return {
                "ok": True,
                "channel": {
                    "id": channel_id,
                    "name": info.get("name", ""),
                    "is_private": bool(info.get("is_private", False)),
                    "is_ext_shared": bool(info.get("is_ext_shared", False)),
                    "is_org_shared": bool(info.get("is_org_shared", False)),
                    "is_im": bool(info.get("is_im", False)),
                    "is_mpim": bool(info.get("is_mpim", False)),
                },
            }

        if method == "conversations.members":
            window, nxt = self._page(list(info.get("members", [])), cursor)
            return {
                "ok": True,
                "members": window,
                "response_metadata": {"next_cursor": nxt},
            }

        if method in ("conversations.history", "conversations.replies"):
            messages = list(channel.get("messages", []))
            if method == "conversations.replies":
                root = params.get("ts", "")
                messages = [
                    m for m in messages
                    if (m.get("thread_ts") or m.get("ts")) == root
                ]
            # Slack returns history newest-first.
            messages = sorted(
                messages, key=lambda m: str(m.get("ts", "")), reverse=True
            )
            window, nxt = self._page(messages, cursor)
            return {
                "ok": True,
                "messages": window,
                "has_more": bool(nxt),
                "response_metadata": {"next_cursor": nxt},
            }

        return {"ok": False, "error": "unknown_method"}

    # ── Server lifecycle ──────────────────────────────────────────────

    def start(self) -> None:
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                pass  # keep the test output clean

            def _respond(self, payload: dict[str, Any], status: int = 200) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if server_ref.send_scope_header:
                    self.send_header("X-OAuth-Scopes", server_ref.granted_scopes)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                parsed = urlparse(self.path)
                if not parsed.path.startswith("/api/"):
                    self._respond({"ok": False, "error": "unknown_method"}, 404)
                    return
                method = parsed.path[len("/api/"):]
                params = {
                    k: v[0] for k, v in parse_qs(parsed.query).items() if v
                }

                server_ref.request_count += 1
                server_ref.requests.append(method)

                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {server_ref.expected_token}":
                    self._respond({"ok": False, "error": "invalid_auth"})
                    return

                if server_ref.request_count <= server_ref.fail_first_n:
                    self._respond({"ok": False, "error": server_ref.fail_error})
                    return

                self._respond(server_ref._dispatch(method, params))

        self._server = HTTPServer((self.host, self.port), Handler)
        if self.port == 0:
            self.port = self._server.server_address[1]
        # Poll faster than the 0.5s default so stop() returns promptly;
        # a per-test half-second of teardown adds up quickly.
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.02),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def reset(self) -> None:
        self.request_count = 0
        self.requests.clear()

    def __enter__(self) -> "MockSlackServer":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

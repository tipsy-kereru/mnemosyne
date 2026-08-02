"""Mock Onyx Ingestion API server for contract testing.

A lightweight stdlib HTTP server that emulates the Onyx
POST /onyx-api/ingestion endpoint. Designed for:

- Contract fixture tests (Phase 5 §6)
- Push integration tests (Phase 1)
- Simulating error conditions (rate limit, auth failure, server error)

Usage in tests::

    server = MockOnyxServer(port=0)  # random free port
    server.start()
    client = OnyxClient(
        base_url=server.base_url,
        api_key="test-key",
        cc_pair_id=1,
        max_retries=1,
        initial_backoff=0.01,
    )
    result = client.ingest(...)
    assert result.status == PushStatus.ACCEPTED
    assert server.received_documents["doc-id"]
    server.stop()

Never used in production. Lives here (not in tests/) so it can be
imported by both unit tests and the CLI ``--dry-run-against-mock`` flag.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class MockOnyxServer:
    """In-process mock of the Onyx Ingestion API.

    Records every received document in :attr:`received_documents` keyed
    by ``document.id``. Configurable to return specific status codes or
    to fail the first N requests (for retry testing).
    """

    def __init__(
        self,
        port: int = 0,
        host: str = "127.0.0.1",
        expected_api_key: str = "test-key",
        fail_first_n: int = 0,
        fail_status: int = 500,
    ) -> None:
        self.host = host
        self.port = port
        self.expected_api_key = expected_api_key
        self.fail_first_n = fail_first_n
        self.fail_status = fail_status
        self.received_documents: dict[str, dict[str, Any]] = {}
        self.request_count = 0
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        actual_port = self._server.server_address[1] if self._server else self.port
        return f"http://{self.host}:{actual_port}"

    def start(self) -> None:
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                pass  # silence default logging

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != "/onyx-api/ingestion":
                    self.send_error(404, "Not found")
                    return

                # Auth check
                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {server_ref.expected_api_key}":
                    self.send_error(401, "Unauthorized")
                    return

                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    self.send_error(400, "Invalid JSON")
                    return

                doc = payload.get("document", {})
                doc_id = doc.get("id", "")
                server_ref.request_count += 1

                # Simulate failures for retry testing
                if server_ref.request_count <= server_ref.fail_first_n:
                    self.send_error(
                        server_ref.fail_status,
                        f"Simulated failure {server_ref.request_count}",
                    )
                    return

                # Record the document
                server_ref.received_documents[doc_id] = payload

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "accepted"}).encode())

        self._server = HTTPServer((self.host, self.port), Handler)
        if self.port == 0:
            self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
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
        """Clear recorded documents and request count."""
        self.received_documents.clear()
        self.request_count = 0

    def __enter__(self) -> "MockOnyxServer":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

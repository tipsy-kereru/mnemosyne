"""HTTP server for the Mnemosyne Knowledge Graph API.

Uses Python stdlib ``http.server`` -- no external framework dependencies.
"""

from __future__ import annotations

import json
import logging
import re
import signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from mnemosyne.graph.knowledge_graph import KnowledgeGraph
from mnemosyne.serve.handlers import APIError, Handlers

logger = logging.getLogger(__name__)

# SPEC-NLQUERY-001 security: cap request body size to bound memory/token cost.
# 64 KiB is generous for ask/chat payloads (questions are capped tighter in
# handlers) while rejecting multi-MB bodies that would flow into GLiNER2 / FTS5
# / the LLM prompt.
MAX_BODY_BYTES = 64 * 1024

# Calling conventions for handler methods:
#   "no_arg"          -> handler()
#   "url_arg"         -> handler(url_args[0])
#   "url_arg_params"  -> handler(url_args[0], params)
#   "url_body"        -> handler(url_args[0], body)
#   "params"          -> handler(params)
#   "body"            -> handler(body)
_CALLConvention = str

# Pre-compiled route patterns: (method, pattern, handler_method_name, calling_convention)
_ROUTES: list[tuple[str, re.Pattern[str], str, _CALLConvention]] = [
    ("GET", re.compile(r"^/api/v1/health$"), "health", "no_arg"),
    ("GET", re.compile(r"^/api/v1/stats$"), "stats", "no_arg"),
    ("GET", re.compile(r"^/api/v1/entities$"), "list_entities", "params"),
    ("GET", re.compile(r"^/api/v1/entities/([^/]+)$"), "get_entity", "url_arg"),
    ("POST", re.compile(r"^/api/v1/entities$"), "create_entity", "body"),
    ("PUT", re.compile(r"^/api/v1/entities/([^/]+)$"), "update_entity", "url_body"),
    ("GET", re.compile(r"^/api/v1/relations$"), "list_relations", "params"),
    ("GET", re.compile(r"^/api/v1/relations/([^/]+)$"), "get_relation", "url_arg"),
    ("POST", re.compile(r"^/api/v1/relations$"), "create_relation", "body"),
    ("POST", re.compile(r"^/api/v1/query$"), "query", "body"),
    ("GET", re.compile(r"^/api/v1/search$"), "search", "params"),
    ("GET", re.compile(r"^/api/v1/projects$"), "list_projects", "no_arg"),
    ("GET", re.compile(r"^/api/v1/projects/([^/]+)$"), "get_project", "url_arg"),
    ("GET", re.compile(r"^/api/v1/wiki/status$"), "wiki_status", "params"),
    ("GET", re.compile(r"^/api/v1/wiki/lint$"), "wiki_lint", "params"),
    # SPEC-NLQUERY-001: NL query + multi-turn chat.
    ("POST", re.compile(r"^/api/v1/ask$"), "ask", "body"),
    ("POST", re.compile(r"^/api/v1/chat$"), "chat", "body"),
    (
        "GET",
        re.compile(r"^/api/v1/chat/sessions$"),
        "chat_list_sessions",
        "params",
    ),
    (
        "GET",
        re.compile(r"^/api/v1/chat/sessions/([^/]+)$"),
        "chat_get_session",
        "url_arg_params",
    ),
    (
        "DELETE",
        re.compile(r"^/api/v1/chat/sessions/([^/]+)$"),
        "chat_archive_session",
        "url_arg_params",
    ),
]


class _RequestHandler(BaseHTTPRequestHandler):
    """Routes incoming HTTP requests to handler methods."""

    handlers: Handlers  # Set by create_server before serving

    # Suppress per-request access log lines (handled via logging instead)
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.debug(format, *args)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    # -- internal helpers ----------------------------------------------------

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = _qs_to_dict(parse_qs(parsed.query))

        for route_method, pattern, handler_name, convention in _ROUTES:
            if method != route_method:
                continue
            m = pattern.match(path)
            if m is None:
                continue

            handler = getattr(self.handlers, handler_name)
            try:
                # Read body for POST/PUT
                body: Dict[str, Any] = {}
                if method in ("POST", "PUT"):
                    body = self._read_json_body()

                # Build positional args from URL captures
                url_args = m.groups()

                # Call handler with appropriate arguments
                status, response = self._invoke(
                    handler, convention, url_args, params, body
                )
                self._send_json(status, response)
            except APIError as exc:
                self._send_json(exc.status, exc.to_dict())
            except Exception:
                logger.exception("Unhandled error in %s %s", method, path)
                self._send_json(500, {"error": "INTERNAL_ERROR",
                                      "message": "Internal server error",
                                      "status": 500})
            return

        self._send_json(404, {"error": "NOT_FOUND",
                              "message": f"Not found: {path}",
                              "status": 404})

    def _invoke(
        self,
        handler: Any,
        convention: _CALLConvention,
        url_args: tuple[str, ...],
        params: Dict[str, str],
        body: Dict[str, Any],
    ) -> tuple[int, Dict[str, Any]]:
        """Call a handler using the route's declared calling convention."""
        if convention == "no_arg":
            return handler()
        if convention == "url_arg":
            return handler(url_args[0])
        if convention == "url_arg_params":
            return handler(url_args[0], params)
        if convention == "url_body":
            return handler(url_args[0], body)
        if convention == "params":
            return handler(params)
        if convention == "body":
            return handler(body)
        raise ValueError(f"Unknown convention: {convention}")

    def _read_json_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        # DoS guard (SPEC-NLQUERY-001 security): reject oversized bodies before
        # allocating/reading them. Raises PAYLOAD_TOO_LARGE (413).
        if content_length > MAX_BODY_BYTES:
            raise APIError(
                "PAYLOAD_TOO_LARGE",
                f"Request body exceeds {MAX_BODY_BYTES} bytes",
                413,
            )
        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise APIError(
                "PARSE_ERROR", f"Invalid JSON: {exc}", 400
            ) from exc

    def _send_json(self, status: int, body: Dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _qs_to_dict(qs: Dict[str, list[str]]) -> Dict[str, str]:
    """Flatten parse_qs result to single-value dict."""
    return {k: v[0] for k, v in qs.items() if v}


def create_server(
    host: str = "127.0.0.1",
    port: int = 57832,
    db_path: Optional[str] = None,
) -> HTTPServer:
    """Create an HTTPServer wired to a KnowledgeGraph at *db_path*.

    The caller is responsible for calling ``server.serve_forever()`` or
    ``server.handle_request()``.
    """
    kg = KnowledgeGraph(db_path)
    handler_obj = Handlers(kg, str(kg.db_path))

    # Inject handlers reference onto the class so every request can see it
    _RequestHandler.handlers = handler_obj

    server = HTTPServer((host, port), _RequestHandler)
    server.timeout = 0.5  # Allows graceful shutdown checks

    logger.info("Mnemosyne API listening on http://%s:%d", host, port)
    return server


def _load_dotenv() -> None:
    try:
        from pathlib import Path
        from dotenv import load_dotenv  # type: ignore[import-not-found]
        current = Path(__file__).resolve().parent
        for _ in range(4):
            env_path = current / ".env"
            if env_path.exists():
                load_dotenv(dotenv_path=env_path)
                break
            current = current.parent
        else:
            load_dotenv()
    except ImportError:
        pass


def serve(
    host: str = "127.0.0.1",
    port: int = 57832,
    db_path: Optional[str] = None,
) -> None:
    """Start the HTTP server and block until interrupted."""
    _load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    server = create_server(host=host, port=port, db_path=db_path)

    # Graceful shutdown on SIGTERM / SIGINT
    def _shutdown(signum: int, _frame: Any) -> None:
        logger.info("Received signal %d, shutting down", signum)
        server.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        logger.info("Server stopped")

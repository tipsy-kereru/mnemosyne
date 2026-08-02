"""Tests for the threaded Mnemosyne HTTP server (Tier 2 hardening).

Verifies that ``mnemosyne serve`` runs on a ``ThreadingHTTPServer`` so
concurrent agent requests don't block each other, that GET (read)
endpoints use the connection pool's ``query_only`` read connections, and
that POST (write) endpoints still mutate via the write connection.

HTTP calls use stdlib ``urllib`` only -- no external dependencies.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request

import pytest
from http.server import ThreadingHTTPServer

from mnemosyne.serve.app import _RequestHandler, _ThreadSafeHandlers, create_server


# ---------------------------------------------------------------------------
# Fixture: ephemeral threaded server on a free port
# ---------------------------------------------------------------------------


@pytest.fixture()
def server(tmp_path):
    """Start the threaded API server in a background thread with a temp DB.

    Yields ``(server, base_url, db_path)`` and shuts the server down on
    teardown, matching the convention used by ``tests/test_serve.py``.
    """
    db_path = str(tmp_path / "threaded.db")
    srv = create_server(host="127.0.0.1", port=0, db_path=db_path)
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    # Give the listener a moment to accept connections.
    time.sleep(0.15)

    yield srv, base, db_path

    srv.shutdown()
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(base: str, path: str) -> tuple[int, dict]:
    """GET ``base + path``; return ``(status, parsed_json)``."""
    try:
        resp = urllib.request.urlopen(base + path)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post(base: str, path: str, data: dict) -> tuple[int, dict]:
    """POST JSON ``data`` to ``base + path``; return ``(status, parsed_json)``."""
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _seed_entity(base: str, eid: str) -> int:
    return _post(
        base,
        "/api/v1/entities",
        {"id": eid, "type": "concept", "name": eid},
    )[0]


# ---------------------------------------------------------------------------
# (4) Server starts / stops cleanly as a ThreadingHTTPServer
# ---------------------------------------------------------------------------


def test_server_is_threading_http_server(server):
    """create_server() returns a ThreadingHTTPServer with daemon threads."""
    srv, _base, _db = server
    assert isinstance(srv, ThreadingHTTPServer)
    assert srv.daemon_threads is True


def test_server_starts_and_responds(server):
    """A freshly started server answers /api/v1/health."""
    _srv, base, _db = server
    status, body = _get(base, "/api/v1/health")
    assert status == 200
    assert body["status"] == "ok"


def test_handlers_route_reads_through_pool(server):
    """The request handlers are the pool-backed _ThreadSafeHandlers subclass."""
    _srv, _base, _db = server
    assert isinstance(_RequestHandler.handlers, _ThreadSafeHandlers)


# ---------------------------------------------------------------------------
# (1) Server handles concurrent GET requests without blocking
# ---------------------------------------------------------------------------


def test_concurrent_gets_all_succeed(server):
    """Many simultaneous GETs all complete and see the committed data."""
    _srv, base, _db = server
    # Seed a deterministic set BEFORE the concurrent reads.
    for i in range(5):
        assert _seed_entity(base, f"e{i}") == 201

    results: list[tuple[int, int]] = []
    errors: list[BaseException] = []
    n = 16

    def worker():
        try:
            status, body = _get(base, "/api/v1/entities")
            results.append((status, body.get("count", -1)))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    elapsed = time.perf_counter() - start

    assert not errors, f"concurrent GETs raised: {errors}"
    assert len(results) == n, "some concurrent GETs did not complete"
    assert all(status == 200 for status, _ in results)
    # Every concurrent reader observed the full committed set.
    assert all(count == 5 for _, count in results), results
    # Sanity: 16 concurrent reads finishing in well under the per-request
    # serial floor would be implausible on a single-threaded server that
    # serialized them; here we just assert it completes promptly.
    assert elapsed < 15.0


def test_concurrent_mixed_read_write(server):
    """Concurrent readers intermixed with concurrent writers complete cleanly."""
    _srv, base, _db = server
    assert _seed_entity(base, "seed") == 201

    errors: list[BaseException] = []

    def reader():
        for _ in range(8):
            try:
                _get(base, "/api/v1/entities")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    def writer(j: int):
        for i in range(8):
            try:
                _post(
                    base,
                    "/api/v1/entities",
                    {"id": f"w{j}-{i}", "type": "concept", "name": f"w{j}-{i}"},
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    threads += [threading.Thread(target=writer, args=(j,)) for j in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert not errors, f"mixed workload raised: {errors}"
    status, body = _get(base, "/api/v1/entities")
    assert status == 200
    # seed (1) + 2 writers * 8 unique ids (16) = 17 committed entities.
    assert body["count"] == 17


# ---------------------------------------------------------------------------
# (2) GET requests use read connections (query_only works)
# ---------------------------------------------------------------------------


def test_read_connection_is_query_only(server):
    """A pooled read connection rejects writes (PRAGMA query_only=1)."""
    _srv, _base, _db = server
    kg = _RequestHandler.handlers.kg
    read_conn = kg.get_read_conn()
    with pytest.raises(sqlite3.OperationalError):
        read_conn.execute("CREATE TABLE _should_fail (x INTEGER)")


def test_get_endpoint_uses_pool_read_connection(server):
    """GET /api/v1/entities is served through kg.get_read_conn()."""
    _srv, base, _db = server
    assert _seed_entity(base, "e1") == 201

    kg = _RequestHandler.handlers.kg
    calls = {"n": 0}
    real = kg.get_read_conn

    def counting():
        calls["n"] += 1
        return real()

    # The request runs in a ThreadingHTTPServer request thread but shares
    # this KG instance, so the instance attribute is observed there too.
    kg.get_read_conn = counting  # type: ignore[method-assign]
    try:
        status, body = _get(base, "/api/v1/entities")
    finally:
        kg.get_read_conn = real  # type: ignore[method-assign]

    assert status == 200
    assert calls["n"] >= 1, "GET /api/v1/entities did not call kg.get_read_conn()"
    assert any(e["id"] == "e1" for e in body["entities"])


# ---------------------------------------------------------------------------
# (3) POST (create entity) still works via the write connection
# ---------------------------------------------------------------------------


def test_post_creates_entity_visible_to_reads(server):
    """A POST creates an entity via the write path, visible to later reads."""
    _srv, base, _db = server
    status, body = _post(
        base,
        "/api/v1/entities",
        {
            "id": "neo",
            "type": "concept",
            "name": "Neo",
            "properties": {"role": "the-one"},
        },
    )
    assert status == 201
    assert body["id"] == "neo"
    assert body["name"] == "Neo"

    # WAL consistency: the committed write is visible to a subsequent read.
    status, body = _get(base, "/api/v1/entities")
    assert status == 200
    ids = [e["id"] for e in body["entities"]]
    assert "neo" in ids

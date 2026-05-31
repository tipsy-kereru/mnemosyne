"""Tests for the Mnemosyne HTTP API server (mnemosyne serve)."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
import pytest

from mnemosyne.serve.app import create_server


# ---------------------------------------------------------------------------
# Fixture: ephemeral HTTP server on a free port
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_server(tmp_path):
    """Start the API server in a background thread with a temp database.

    Yields (base_url, db_path) and shuts the server down on teardown.
    """
    db_path = str(tmp_path / "test.db")
    server = create_server(host="127.0.0.1", port=0, db_path=db_path)
    actual_port = server.server_address[1]
    base_url = f"http://127.0.0.1:{actual_port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Give the server a moment to start accepting connections
    time.sleep(0.15)

    yield base_url, db_path

    server.shutdown()
    thread.join(timeout=5)


# -- Helpers ----------------------------------------------------------------


def _get(url: str) -> tuple[int, dict]:
    """GET *url* and return (status, parsed_json)."""
    try:
        resp = urllib.request.urlopen(url)
        body = json.loads(resp.read())
        return resp.status, body
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read())
        return exc.code, body


def _post(url: str, data: dict) -> tuple[int, dict]:
    """POST JSON *data* to *url* and return (status, parsed_json)."""
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        resp = urllib.request.urlopen(req)
        body = json.loads(resp.read())
        return resp.status, body
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read())
        return exc.code, body


def _put(url: str, data: dict) -> tuple[int, dict]:
    """PUT JSON *data* to *url* and return (status, parsed_json)."""
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="PUT"
    )
    try:
        resp = urllib.request.urlopen(req)
        body = json.loads(resp.read())
        return resp.status, body
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read())
        return exc.code, body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """AC-S1-001: Health endpoint returns 200."""

    def test_health_returns_ok(self, api_server):
        base_url, _ = api_server
        status, body = _get(f"{base_url}/api/v1/health")
        assert status == 200
        assert body["status"] == "ok"
        assert "version" in body


class TestStatsEndpoint:
    def test_stats_returns_graph_stats(self, api_server):
        base_url, _ = api_server
        status, body = _get(f"{base_url}/api/v1/stats")
        assert status == 200
        assert "entities" in body
        assert "relations" in body


class TestEntityCRUD:
    """AC-S1-002: Entity CRUD round-trip works via HTTP."""

    def test_create_and_read_entity(self, api_server):
        base_url, _ = api_server

        # Create
        create_data = {
            "id": "fn-parse-001",
            "type": "function",
            "name": "parse_config",
            "properties": {"language": "python", "complexity": 3},
        }
        status, created = _post(f"{base_url}/api/v1/entities", create_data)
        assert status == 201
        assert created["id"] == "fn-parse-001"
        assert created["name"] == "parse_config"
        assert created["properties"]["language"] == "python"

        # Read
        status, fetched = _get(f"{base_url}/api/v1/entities/fn-parse-001")
        assert status == 200
        assert fetched["id"] == "fn-parse-001"
        assert fetched["name"] == "parse_config"

    def test_update_entity(self, api_server):
        base_url, _ = api_server

        # Create first
        _post(
            f"{base_url}/api/v1/entities",
            {"id": "fn-update-001", "type": "function", "name": "old_name"},
        )

        # Update
        status, updated = _put(
            f"{base_url}/api/v1/entities/fn-update-001",
            {"name": "new_name", "properties": {"updated": True}},
        )
        assert status == 200
        assert updated["name"] == "new_name"
        assert updated["properties"]["updated"] is True
        assert updated["version"] == 2

    def test_list_entities(self, api_server):
        base_url, _ = api_server

        # Create two entities
        _post(
            f"{base_url}/api/v1/entities",
            {"id": "fn-list-1", "type": "function", "name": "func_a"},
        )
        _post(
            f"{base_url}/api/v1/entities",
            {"id": "cls-list-1", "type": "class", "name": "ClassB"},
        )

        # List all
        status, body = _get(f"{base_url}/api/v1/entities")
        assert status == 200
        assert body["count"] >= 2

        # Filter by type
        status, body = _get(
            f"{base_url}/api/v1/entities?{urllib.parse.urlencode({'type': 'function'})}"
        )
        assert status == 200
        assert all(e["type"] == "function" for e in body["entities"])

    def test_missing_entity_returns_404(self, api_server):
        base_url, _ = api_server
        status, body = _get(f"{base_url}/api/v1/entities/nonexistent-id")
        assert status == 404
        assert body["error"] == "NOT_FOUND"

    def test_create_entity_validation_error(self, api_server):
        base_url, _ = api_server
        status, body = _post(
            f"{base_url}/api/v1/entities", {"id": "incomplete"}
        )
        assert status == 422
        assert body["error"] == "VALIDATION_ERROR"


class TestRelationCRUD:
    def test_create_and_read_relation(self, api_server):
        base_url, _ = api_server

        # Create two entities first
        _post(
            f"{base_url}/api/v1/entities",
            {"id": "src-1", "type": "function", "name": "caller"},
        )
        _post(
            f"{base_url}/api/v1/entities",
            {"id": "tgt-1", "type": "function", "name": "callee"},
        )

        # Create relation
        status, created = _post(
            f"{base_url}/api/v1/relations",
            {
                "id": "rel-calls-1",
                "source_id": "src-1",
                "target_id": "tgt-1",
                "relation_type": "calls",
            },
        )
        assert status == 201
        assert created["relation_type"] == "calls"

        # Read relation
        status, fetched = _get(f"{base_url}/api/v1/relations/rel-calls-1")
        assert status == 200
        assert fetched["id"] == "rel-calls-1"

    def test_list_relations_by_type(self, api_server):
        base_url, _ = api_server

        _post(
            f"{base_url}/api/v1/entities",
            {"id": "rl-src", "type": "function", "name": "a"},
        )
        _post(
            f"{base_url}/api/v1/entities",
            {"id": "rl-tgt", "type": "function", "name": "b"},
        )
        _post(
            f"{base_url}/api/v1/relations",
            {
                "id": "rel-uses-1",
                "source_id": "rl-src",
                "target_id": "rl-tgt",
                "relation_type": "uses",
            },
        )

        status, body = _get(
            f"{base_url}/api/v1/relations?{urllib.parse.urlencode({'type': 'uses'})}"
        )
        assert status == 200
        assert any(r["relation_type"] == "uses" for r in body["relations"])

    def test_missing_relation_returns_404(self, api_server):
        base_url, _ = api_server
        status, body = _get(f"{base_url}/api/v1/relations/nonexistent")
        assert status == 404


class TestQueryEndpoint:
    """AC-S1-003: Query endpoint returns results."""

    def test_query_entities(self, api_server):
        base_url, _ = api_server

        _post(
            f"{base_url}/api/v1/entities",
            {"id": "q-fn-1", "type": "function", "name": "parse_config"},
        )

        status, body = _post(
            f"{base_url}/api/v1/query",
            {"query": "entity:function[parse_config]"},
        )
        assert status == 200
        assert body["type"] == "entity_query"
        assert body["count"] >= 1
        found = [e for e in body["results"] if e["id"] == "q-fn-1"]
        assert len(found) == 1

    def test_query_missing_field(self, api_server):
        base_url, _ = api_server
        status, body = _post(f"{base_url}/api/v1/query", {})
        assert status == 422
        assert body["error"] == "VALIDATION_ERROR"


class TestSearchEndpoint:
    def test_search_entities(self, api_server):
        base_url, _ = api_server

        _post(
            f"{base_url}/api/v1/entities",
            {"id": "s-auth-1", "type": "function", "name": "authenticate_user"},
        )

        status, body = _get(
            f"{base_url}/api/v1/search?{urllib.parse.urlencode({'q': 'authenticate'})}"
        )
        assert status == 200
        assert body["count"] >= 1

    def test_search_missing_param(self, api_server):
        base_url, _ = api_server
        status, body = _get(f"{base_url}/api/v1/search")
        assert status == 422


class TestProjectsEndpoint:
    def test_list_projects_empty(self, api_server):
        base_url, _ = api_server
        status, body = _get(f"{base_url}/api/v1/projects")
        assert status == 200
        assert body["count"] == 0

    def test_get_missing_project(self, api_server):
        base_url, _ = api_server
        status, body = _get(f"{base_url}/api/v1/projects/deadbeef")
        assert status == 404


class TestWikiEndpoint:
    def test_wiki_status(self, api_server):
        base_url, _ = api_server
        status, body = _get(f"{base_url}/api/v1/wiki/status")
        assert status == 200
        assert "wiki_root" in body

    def test_wiki_lint(self, api_server):
        base_url, _ = api_server
        status, body = _get(f"{base_url}/api/v1/wiki/lint")
        assert status == 200
        assert "ok" in body


class TestNotFound:
    def test_unknown_path_returns_404(self, api_server):
        base_url, _ = api_server
        status, body = _get(f"{base_url}/api/v1/nonexistent")
        assert status == 404
        assert body["error"] == "NOT_FOUND"

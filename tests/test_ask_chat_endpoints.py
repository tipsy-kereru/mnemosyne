"""REQ-NL-004: HTTP /ask + /chat + sessions endpoints (integration)."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from mnemosyne.serve.app import create_server


@pytest.fixture()
def api(tmp_path):
    db_path = str(tmp_path / "ask_chat.db")
    server = create_server(host="127.0.0.1", port=0, db_path=db_path)
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.15)
    yield base
    server.shutdown()
    thread.join(timeout=5)


def _post(base: str, path: str, data: dict) -> tuple[int, dict]:
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        base + path, data=payload, headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _get(base: str, path: str) -> tuple[int, dict]:
    try:
        resp = urllib.request.urlopen(base + path)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _delete(base: str, path: str) -> tuple[int, dict]:
    req = urllib.request.Request(base + path, method="DELETE")
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_ask_returns_answer_and_plan(api: str) -> None:
    status, body = _post(api, "/api/v1/ask", {"question": "hello world"})
    assert status == 200
    assert "answer" in body
    assert "citations" in body
    assert body["plan"]["intent"] in (
        "search", "entity_lookup", "relation_query", "path_query", "longdoc_retrieve"
    )


def test_ask_missing_question_is_422(api: str) -> None:
    status, _ = _post(api, "/api/v1/ask", {})
    assert status == 422


def test_chat_creates_session_and_turn(api: str) -> None:
    status, body = _post(api, "/api/v1/chat", {"message": "hello"})
    assert status == 200
    assert "session_id" in body and body["session_id"]
    assert "turn_id" in body and body["turn_id"]


def test_chat_resume_appends_turns(api: str) -> None:
    _, first = _post(api, "/api/v1/chat", {"message": "first"})
    sid = first["session_id"]
    status, second = _post(api, "/api/v1/chat", {"message": "second", "session_id": sid})
    assert status == 200
    assert second["session_id"] == sid
    # Two user + two assistant turns = 4.
    status, meta = _get(api, f"/api/v1/chat/sessions/{sid}")
    assert status == 200
    assert meta["count"] == 4


def test_chat_resume_unknown_session_is_404(api: str) -> None:
    status, _ = _post(api, "/api/v1/chat", {"message": "x", "session_id": "ghost"})
    assert status == 404


def test_list_sessions_filtered_by_project(api: str) -> None:
    _post(api, "/api/v1/chat", {"message": "m", "project": "p-hash-1"})
    _post(api, "/api/v1/chat", {"message": "m", "project": "p-hash-2"})
    status, body = _get(api, "/api/v1/chat/sessions?project=p-hash-1")
    assert status == 200
    assert body["count"] == 1


def test_delete_session_is_tombstone_not_row_delete(api: str) -> None:
    _, created = _post(api, "/api/v1/chat", {"message": "m"})
    sid = created["session_id"]
    status, body = _delete(api, f"/api/v1/chat/sessions/{sid}")
    assert status == 200
    assert body["deleted"] is False
    assert body["status"] == "archived"
    # Session + turns still retrievable.
    status, meta = _get(api, f"/api/v1/chat/sessions/{sid}")
    assert status == 200
    assert meta["session"]["status"] == "archived"
    assert meta["count"] >= 2


def test_delete_unknown_session_is_404(api: str) -> None:
    status, _ = _delete(api, "/api/v1/chat/sessions/ghost")
    assert status == 404

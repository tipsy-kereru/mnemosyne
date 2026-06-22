"""REQ-NL-006/007: ChatStore append-only persistence + context window."""

from __future__ import annotations

import sqlite3
from typing import List

import pytest

from mnemosyne.query.chat_store import (
    ChatStore,
    build_context_window,
    init_chat_schema,
)


@pytest.fixture()
def store(tmp_path) -> ChatStore:
    conn = sqlite3.connect(str(tmp_path / "chat.db"))
    conn.row_factory = sqlite3.Row
    return ChatStore(conn)


def test_idempotent_ddl(tmp_path) -> None:
    """init_chat_schema twice must not error (sqlite_master guard)."""
    conn = sqlite3.connect(str(tmp_path / "idem.db"))
    init_chat_schema(conn)
    init_chat_schema(conn)  # second call must be a no-op
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "chat_sessions" in tables
    assert "chat_turns" in tables


def test_create_and_list_session(store: ChatStore) -> None:
    sid = store.create_session(project_hash="proj-a")
    sessions = store.list_sessions(project_hash="proj-a")
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == sid
    assert sessions[0]["status"] == "active"


def test_append_turn_preserves_order(store: ChatStore) -> None:
    sid = store.create_session()
    t1 = store.append_turn(sid, "user", "hello")
    t2 = store.append_turn(sid, "assistant", "hi", [{"type": "entity", "id": "e1"}])
    turns = store.list_turns(sid)
    assert [t["turn_id"] for t in turns] == [t1, t2]
    assert turns[1]["citations"] == [{"type": "entity", "id": "e1"}]


def test_archive_is_tombstone_not_delete(store: ChatStore) -> None:
    """REQ-NL-006: archive flips status; chat_turns rows are never deleted."""
    sid = store.create_session()
    store.append_turn(sid, "user", "q")
    assert store.archive_session(sid) is True
    # Session row still exists, now archived.
    meta = store.get_session(sid)
    assert meta is not None
    assert meta["status"] == "archived"
    # Turns are still present.
    assert len(store.list_turns(sid)) == 1
    # Idempotent: second archive reports already-archived.
    assert store.archive_session(sid) is False


def test_no_delete_statement_in_source() -> None:
    """AC-6: zero DELETE FROM chat_turns in the new code path."""
    import mnemosyne.query.chat_store as mod
    import inspect

    src = inspect.getsource(mod)
    assert "DELETE FROM chat_turns" not in src
    assert "DELETE FROM chat_sessions" not in src


def test_list_sessions_filters_by_project(store: ChatStore) -> None:
    store.create_session(project_hash="p1")
    store.create_session(project_hash="p2")
    assert len(store.list_sessions(project_hash="p1")) == 1


def test_context_window_defaults_to_ten(monkeypatch, store: ChatStore) -> None:
    monkeypatch.delenv("MNEMOSYNE_CHAT_CONTEXT_TURNS", raising=False)
    turns: List[dict] = [{"role": "user", "content": f"m{i}"} for i in range(15)]
    window = build_context_window(turns)
    # Last 10 turns + 1 summary line for the 5 omitted.
    assert "[prior 5 turns summarized]" in window
    assert "m5" in window and "m14" in window
    assert "m4" not in window


def test_context_window_env_override(monkeypatch) -> None:
    monkeypatch.setenv("MNEMOSYNE_CHAT_CONTEXT_TURNS", "2")
    turns = [{"role": "user", "content": f"m{i}"} for i in range(4)]
    window = build_context_window(turns)
    assert "[prior 2 turns summarized]" in window
    assert "m3" in window and "m0" not in window

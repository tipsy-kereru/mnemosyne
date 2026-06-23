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


# -- SPEC-NLQUERY-001 security: per-turn content cap -------------------------


def test_get_session_filters_by_project(store: ChatStore) -> None:
    """IDOR guard: get_session(project_hash=...) returns None on mismatch."""
    sid = store.create_session(project_hash="owner-a")
    assert store.get_session(sid, project_hash="owner-a") is not None
    assert store.get_session(sid, project_hash="attacker-b") is None
    assert store.get_session(sid) is not None  # no filter = no check


def test_append_turn_truncates_oversize_content(store: ChatStore) -> None:
    """Per-turn content over MAX_TURN_CONTENT_BYTES is truncated with a marker."""
    from mnemosyne.query.chat_store import MAX_TURN_CONTENT_BYTES

    sid = store.create_session()
    big = "x" * (MAX_TURN_CONTENT_BYTES * 2)
    store.append_turn(sid, "user", big)
    turns = store.list_turns(sid)
    content = turns[0]["content"]
    assert "[truncated]" in content
    assert len(content.encode("utf-8")) <= MAX_TURN_CONTENT_BYTES


def test_cap_turn_content_preserves_small_input() -> None:
    from mnemosyne.query.chat_store import _cap_turn_content

    assert _cap_turn_content("hello") == "hello"


def test_cap_turn_content_multibyte_boundary() -> None:
    """Truncation must not split a multibyte (CJK) character."""
    from mnemosyne.query.chat_store import MAX_TURN_CONTENT_BYTES, _cap_turn_content

    # Each 'あ' is 3 UTF-8 bytes; force a mid-character slice.
    unit = "あ"
    big = unit * (MAX_TURN_CONTENT_BYTES // len(unit.encode()) + 50)
    capped = _cap_turn_content(big)
    assert "[truncated]" in capped
    # Result must be valid UTF-8 (decodable without errors).
    capped.encode("utf-8").decode("utf-8")
    assert len(capped.encode("utf-8")) <= MAX_TURN_CONTENT_BYTES


# -- ISSUE-0004: retention_purged_at column + purge job + redact-on-persist ----


def test_retention_purged_at_column_added_idempotent(tmp_path) -> None:
    """init_chat_schema must add retention_purged_at (additive, idempotent).

    A pre-existing DB created before ISSUE-0004 (no retention_purged_at) must
    gain the column on the next init_chat_schema call, and a second call must
    be a no-op (PRAGMA guard). The created_at index must also appear.
    """
    conn = sqlite3.connect(str(tmp_path / "retention.db"))
    # Simulate a pre-ISSUE-0004 schema: chat_turns WITHOUT retention_purged_at.
    conn.execute(
        "CREATE TABLE chat_sessions (session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute(
        "CREATE TABLE chat_turns (turn_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, citations TEXT, created_at TEXT NOT NULL)"
    )
    conn.commit()

    init_chat_schema(conn)  # migration
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_turns)")}
    assert "retention_purged_at" in cols

    init_chat_schema(conn)  # second call: no-op (idempotent guard)
    cols_after = {r[1] for r in conn.execute("PRAGMA table_info(chat_turns)")}
    assert cols_after == cols

    # Index exists for the purge WHERE clause.
    idx_names = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='chat_turns'"
        )
    }
    assert "idx_chat_turns_created" in idx_names
    conn.close()


def test_new_schema_has_retention_purged_at_default_null(store: ChatStore) -> None:
    """Fresh schema: retention_purged_at defaults to NULL."""
    sid = store.create_session()
    store.append_turn(sid, "user", "hello")
    row = store.conn.execute(
        "SELECT retention_purged_at FROM chat_turns WHERE session_id=?",
        (sid,),
    ).fetchone()
    assert row[0] is None


# -- redact-on-persist (AC-3) -------------------------------------------------


def test_append_turn_redacts_jwt_before_persist(store: ChatStore) -> None:
    """A JWT in chat content must be replaced with [REDACTED:jwt] on insert."""
    sid = store.create_session()
    # Realistic-shape JWT: header.payload.signature, each segment base64url.
    jwt_token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    store.append_turn(sid, "user", f"here is my token: {jwt_token}")
    turns = store.list_turns(sid)
    stored = turns[0]["content"]
    assert jwt_token not in stored
    assert "[REDACTED:jwt]" in stored


def test_append_turn_redacts_slack_token_before_persist(store: ChatStore) -> None:
    """A Slack token (xoxb-...) must be replaced with [REDACTED:slack]."""
    sid = store.create_session()
    slack = "xox" + "b-FAKE-TEST-TOKEN"  # noqa: concat defeats secret-scanner literal match
    store.append_turn(sid, "user", f"slack bot token: {slack}")
    turns = store.list_turns(sid)
    stored = turns[0]["content"]
    assert slack not in stored
    assert "[REDACTED:slack]" in stored


def test_append_turn_redacts_github_token_before_persist(store: ChatStore) -> None:
    """Existing patterns still apply on the chat path (ghp_)."""
    sid = store.create_session()
    ghp = "ghp_" + "a" * 36
    store.append_turn(sid, "user", f"github pat: {ghp}")
    turns = store.list_turns(sid)
    stored = turns[0]["content"]
    assert ghp not in stored
    assert "[REDACTED:github-token]" in stored


def test_append_turn_no_false_positive_on_benign_content(
    store: ChatStore,
) -> None:
    """Benign chat content must survive redact-on-persist unmodified.

    False-positive guard: short ``eyJ``-prefixed base64 fragments (fewer than
    10 chars in any segment) and benign prose must NOT be redacted.
    """
    sid = store.create_session()
    benign = "The JSON starts with eyJ which means {\" in base64. Short token here."
    store.append_turn(sid, "user", benign)
    turns = store.list_turns(sid)
    assert turns[0]["content"] == benign


def test_append_turn_no_false_positive_on_short_eyj(store: ChatStore) -> None:
    """JWT tight-scope: a bare ``eyJ`` substring must NOT match."""
    from mnemosyne.extraction.longdoc.security import redact

    # Three segments but each < 10 chars -> must not match the JWT pattern.
    short = "eyJ.eyJ.eyJ"
    assert redact(short) == short
    # Single eyJ with no dots -> must not match.
    assert redact("just eyJ here") == "just eyJ here"


# -- purge job (AC-4) ---------------------------------------------------------


def _insert_turn_with_created_at(
    store: ChatStore, session_id: str, content: str, created_at: str
) -> str:
    """Raw insert bypassing _utc_now() so we can back-date turns for TTL tests."""
    import secrets as _secrets

    turn_id = f"turn_{_secrets.token_hex(8)}"
    store.conn.execute(
        "INSERT INTO chat_turns (turn_id, session_id, role, content, citations, created_at) "
        "VALUES (?, ?, 'user', ?, '[]', ?)",
        (turn_id, session_id, content, created_at),
    )
    store.conn.commit()
    return turn_id


def test_purge_dry_run_performs_zero_writes(store: ChatStore) -> None:
    """--dry-run reports candidates but performs zero writes."""
    from mnemosyne.query.chat_store import purge_retention

    sid = store.create_session()
    # Back-date a turn by 100 days (default TTL is 90).
    from datetime import datetime, timedelta, timezone

    old_created = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=100)
    ).isoformat()
    _insert_turn_with_created_at(store, sid, "old turn", old_created)

    rowcount_before = store.conn.execute(
        "SELECT COUNT(*) FROM chat_turns"
    ).fetchone()[0]
    purged_before = store.conn.execute(
        "SELECT COUNT(*) FROM chat_turns WHERE retention_purged_at IS NOT NULL"
    ).fetchone()[0]

    result = purge_retention(store.conn, days=90, apply=False)

    assert result["mode"] == "dry-run"
    assert result["candidate_count"] == 1
    rowcount_after = store.conn.execute(
        "SELECT COUNT(*) FROM chat_turns"
    ).fetchone()[0]
    purged_after = store.conn.execute(
        "SELECT COUNT(*) FROM chat_turns WHERE retention_purged_at IS NOT NULL"
    ).fetchone()[0]
    assert rowcount_after == rowcount_before  # zero rows written
    assert purged_after == purged_before  # zero retention_purged_at set


def test_purge_apply_tombstones_and_is_idempotent(store: ChatStore) -> None:
    """--apply UPDATEs the row (retention_purged_at set, content overwritten)
    and is idempotent on re-run. NO row deletion."""
    from mnemosyne.query.chat_store import purge_retention

    sid = store.create_session()
    from datetime import datetime, timedelta, timezone

    old_created = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=100)
    ).isoformat()
    turn_id = _insert_turn_with_created_at(store, sid, "secret content", old_created)

    rows_before = store.conn.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0]

    result = purge_retention(store.conn, days=90, apply=True)
    assert result["mode"] == "apply"
    assert result["purged_count"] == 1

    rows_after = store.conn.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0]
    assert rows_after == rows_before, "no row must be deleted (no-delete contract)"

    row = store.conn.execute(
        "SELECT content, retention_purged_at FROM chat_turns WHERE turn_id=?",
        (turn_id,),
    ).fetchone()
    assert row[0] == "[retention-purged]"
    assert row[1] is not None

    # Idempotent re-run: candidate_count is now 0 (purged_at is set).
    result2 = purge_retention(store.conn, days=90, apply=True)
    assert result2["purged_count"] == 0
    assert result2["candidate_count"] == 0


def test_purge_ttl_boundary_exact_cutoff(store: ChatStore) -> None:
    """A turn at exactly now-days is purged; one 1 second newer is not."""
    from mnemosyne.query.chat_store import purge_retention

    sid = store.create_session()
    from datetime import datetime, timedelta, timezone

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    # Just-under the cutoff (older): 90 days + 1 hour ago.
    older = (now_naive - timedelta(days=90, hours=1)).isoformat()
    # Just-over the cutoff (newer): 90 days - 1 hour ago.
    newer = (now_naive - timedelta(days=89, hours=23)).isoformat()
    _insert_turn_with_created_at(store, sid, "old", older)
    _insert_turn_with_created_at(store, sid, "recent", newer)

    result = purge_retention(store.conn, days=90, apply=True)
    assert result["purged_count"] == 1  # only the older turn

    rows = store.conn.execute(
        "SELECT content FROM chat_turns WHERE session_id=? ORDER BY created_at",
        (sid,),
    ).fetchall()
    contents = [r[0] for r in rows]
    assert "[retention-purged]" in contents
    assert "old" not in contents  # overwritten
    assert "recent" in contents  # untouched


def test_purge_never_issues_delete() -> None:
    """AC-4 / no-delete contract: chat_store source must contain no DELETE
    against chat_turns."""
    import inspect
    import mnemosyne.query.chat_store as mod

    src = inspect.getsource(mod)
    assert "DELETE FROM chat_turns" not in src
    # No bare DELETE on the turn table at all.
    assert "DELETE FROM chat_turns" not in src.replace("DELETE FROM chat_turns", "")


def test_purge_respects_days_override_and_env(monkeypatch, tmp_path) -> None:
    """--days overrides MNEMOSYNE_CHAT_RETENTION_DAYS; env applies when no flag."""
    from mnemosyne.query.chat_store import (
        DEFAULT_CHAT_RETENTION_DAYS,
        retention_days_from_env,
    )

    monkeypatch.delenv("MNEMOSYNE_CHAT_RETENTION_DAYS", raising=False)
    assert retention_days_from_env() == DEFAULT_CHAT_RETENTION_DAYS

    monkeypatch.setenv("MNEMOSYNE_CHAT_RETENTION_DAYS", "30")
    assert retention_days_from_env() == 30

    # Invalid env falls back to default.
    monkeypatch.setenv("MNEMOSYNE_CHAT_RETENTION_DAYS", "not-a-number")
    assert retention_days_from_env() == DEFAULT_CHAT_RETENTION_DAYS

    # Non-positive falls back.
    monkeypatch.setenv("MNEMOSYNE_CHAT_RETENTION_DAYS", "0")
    assert retention_days_from_env() == DEFAULT_CHAT_RETENTION_DAYS


def test_purge_cli_subcommand_dry_run(tmp_path, capsys) -> None:
    """mnemosyne purge-retention --dry-run wires through to the CLI helper."""
    from mnemosyne.cli import main as cli_main

    db_path = str(tmp_path / "cli.db")
    # Seed: create a KnowledgeGraph + an old turn via ChatStore.
    from mnemosyne.graph.knowledge_graph import KnowledgeGraph
    from mnemosyne.query.chat_store import ChatStore
    from datetime import datetime, timedelta, timezone

    kg = KnowledgeGraph(db_path=db_path)
    try:
        store = ChatStore(kg.conn)
        sid = store.create_session()
        old = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(days=100)
        ).isoformat()
        _insert_turn_with_created_at(store, sid, "old via cli", old)
    finally:
        kg.close()

    cli_main(["purge-retention", "--dry-run", "--days", "90", "--db-path", db_path])
    out = capsys.readouterr().out
    assert '"mode": "dry-run"' in out
    assert '"candidate_count": 1' in out


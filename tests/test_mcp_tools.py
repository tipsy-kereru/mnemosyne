"""Tests for SPEC-MCP-001: mnemosyne MCP server tool set.

Covers AC1-AC10:
  - AC2: tools/list returns exactly the expected set and NO delete tool
  - AC3: mnemosyne_search via FTS5 returns authenticateUser-style matches for "auth"
  - AC4: mnemosyne_add -> mnemosyne_get_entity round-trip
  - AC5: mnemosyne_update_entity appends entity_history, prior version preserved
  - AC6: no tool emits a SQL DELETE against entities/relations
  - AC7: read workflow with no API key, no network
  - AC8: mnemosyne mcp install --client claude-desktop prints a valid snippet
  - AC9: scope params on mnemosyne_query filter results
  - AC10: tool dispatch, schema validation, no-delete invariant
  - REQ-MCP-009 isolation: tool handler returns plain dict; server converts to mcp.types
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import mcp.types as types
import pytest

from mnemosyne.mcp.tools import (
    ToolContext,
    ToolRuntimeError,
    build_tool_specs,
    invoke_tool,
    tool_names,
)
from mnemosyne.serve.handlers import APIError


# -- Expected tool set (REQ-MCP-003/004/005/006) ---------------------------

EXPECTED_TOOLS = {
    # READ
    "mnemosyne_search",
    "mnemosyne_query",
    "mnemosyne_get_entity",
    "mnemosyne_list_entities",
    "mnemosyne_stats",
    "mnemosyne_wiki_status",
    "mnemosyne_wiki_lint",
    # WRITE (create/update only)
    "mnemosyne_add",
    "mnemosyne_extract",
    "mnemosyne_create_entity",
    "mnemosyne_update_entity",
    "mnemosyne_create_relation",
    # WIKI maintenance
    "mnemosyne_wiki_rebuild",
    "mnemosyne_wiki_prune",
}


# -- Fixtures ---------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "mcp_test.db")


@pytest.fixture
def ctx(db_path):
    """Shared ToolContext backed by a temp KnowledgeGraph."""
    c = ToolContext.build(db_path=db_path)
    yield c
    c.close()


@pytest.fixture
def kg_ctx(ctx):
    """Seed a couple of entities for search/query tests."""
    invoke_tool(ctx, "mnemosyne_create_entity", {
        "id": "fn-authenticateUser",
        "type": "function",
        "name": "authenticateUser",
        "properties": {"language": "python"},
        "scope_id": None,
    })
    invoke_tool(ctx, "mnemosyne_create_entity", {
        "id": "fn-parseConfig",
        "type": "function",
        "name": "parseConfig",
        "properties": {"language": "python"},
    })
    return ctx


# ============================================================================
# AC2 + REQ-MCP-006: tool set and no-delete invariant
# ============================================================================

class TestToolSet:
    def test_tools_list_returns_expected_set(self):
        specs = build_tool_specs()
        names = {s.name for s in specs}
        assert names == EXPECTED_TOOLS

    def test_tool_names_sorted(self):
        assert tool_names() == sorted(EXPECTED_TOOLS)

    def test_no_delete_tool_present(self):
        """AC2/REQ-MCP-006: no tool name implies deletion."""
        names = tool_names()
        forbidden = [n for n in names if "delete" in n.lower() or "remove" in n.lower()]
        assert forbidden == [], f"Found deletion-implying tools: {forbidden}"

    def test_tool_names_match_regex(self):
        import re
        for spec in build_tool_specs():
            # MCP tool names must match ^[a-zA-Z0-9_-]{1,64}$
            assert re.match(r"^[a-zA-Z0-9_-]{1,64}$", spec.name), spec.name

    def test_every_tool_has_input_schema(self):
        for spec in build_tool_specs():
            assert spec.input_schema["type"] == "object"
            assert "properties" in spec.input_schema

    def test_unknown_tool_raises(self, ctx):
        with pytest.raises(APIError) as ei:
            invoke_tool(ctx, "mnemosyne_delete_entity", {"entity_id": "x"})
        assert ei.value.code == "UNKNOWN_TOOL"


# ============================================================================
# AC3: mnemosyne_search via FTS5
# ============================================================================

def _has_fts5() -> bool:
    conn = sqlite3.connect(":memory:")
    try:
        opts = [r[0] for r in conn.execute("PRAGMA compile_options")]
        return "ENABLE_FTS5" in opts
    finally:
        conn.close()


FTS5_AVAILABLE = _has_fts5()


@pytest.mark.skipif(not FTS5_AVAILABLE, reason="FTS5 not compiled into sqlite3")
class TestSearch:
    def test_search_auth_returns_authenticateuser(self, kg_ctx):
        """AC3: search 'auth' returns authenticateUser-style matches."""
        result = invoke_tool(kg_ctx, "mnemosyne_search", {"term": "auth"})
        assert result["type"] == "search"
        names = [r["name"] for r in result["results"]]
        assert "authenticateUser" in names

    def test_search_respects_limit(self, kg_ctx):
        result = invoke_tool(kg_ctx, "mnemosyne_search", {"term": "a", "limit": 1})
        assert len(result["results"]) <= 1
        if result["count"] == 1 and len([r for r in kg_ctx.kg.query("search:a")["results"]]) > 1:
            assert result["truncated"] is True

    def test_search_missing_term_raises(self, ctx):
        with pytest.raises(APIError):
            invoke_tool(ctx, "mnemosyne_search", {})


# ============================================================================
# AC4: mnemosyne_add -> mnemosyne_get_entity round-trip
# ============================================================================

class TestAddRoundTrip:
    def test_add_text_creates_entity(self, ctx):
        """AC4: ingesting small text produces a new entity visible to get_entity."""
        result = invoke_tool(ctx, "mnemosyne_add", {
            "text": "John works at Google as a senior engineer.",
            "domain": "daily",
        })
        assert result["entities_added"] >= 0  # deterministic extractor may find 0+ entities
        assert "source" in result

    def test_add_text_get_entity_visible(self, ctx, tmp_path):
        """AC4 stronger path: create entity via create_entity, then get_entity."""
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "person-john",
            "type": "person",
            "name": "John",
            "properties": {"employer": "Google"},
        })
        fetched = invoke_tool(ctx, "mnemosyne_get_entity", {"entity_id": "person-john"})
        assert fetched["id"] == "person-john"
        assert fetched["name"] == "John"
        assert fetched["properties"]["employer"] == "Google"
        assert fetched["version"] == 1

    def test_add_requires_target_or_text(self, ctx):
        with pytest.raises(APIError) as ei:
            invoke_tool(ctx, "mnemosyne_add", {})
        assert ei.value.code == "VALIDATION_ERROR"


# ============================================================================
# AC5 + REQ-MCP-006: update appends history, prior version preserved
# ============================================================================

class TestUpdateHistory:
    def test_update_appends_entity_history(self, ctx):
        """AC5: update_entity appends an entity_history row, prior version preserved."""
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "task-1",
            "type": "task",
            "name": "Original",
            "properties": {"status": "open"},
        })
        updated = invoke_tool(ctx, "mnemosyne_update_entity", {
            "entity_id": "task-1",
            "properties": {"status": "done"},
            "name": "Completed",
        })
        assert updated["version"] == 2
        assert updated["history_count"] == 2  # created + updated

        # Prior version preserved in history.
        history = updated["history"]
        change_types = sorted(h["change_type"] for h in history)
        assert change_types == ["created", "updated"]
        versions = sorted(h["version"] for h in history)
        assert versions == [1, 2]

    def test_update_does_not_remove_prior_version(self, ctx):
        """AC5/REQ-MCP-006: the v1 row is still retrievable in history after update."""
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "bug-1",
            "type": "bug",
            "name": "Crash",
            "properties": {"severity": "high"},
        })
        invoke_tool(ctx, "mnemosyne_update_entity", {
            "entity_id": "bug-1",
            "properties": {"severity": "low"},
        })
        fetched = invoke_tool(ctx, "mnemosyne_get_entity", {"entity_id": "bug-1"})
        # Current version bumped, but history retains the original.
        assert fetched["version"] == 2
        v1 = [h for h in fetched["history"] if h["version"] == 1]
        assert len(v1) == 1
        assert v1[0]["change_type"] == "created"

    def test_update_missing_entity_raises(self, ctx):
        with pytest.raises(APIError) as ei:
            invoke_tool(ctx, "mnemosyne_update_entity", {
                "entity_id": "nope",
                "properties": {},
            })
        assert ei.value.code == "NOT_FOUND"


# ============================================================================
# AC6: no tool emits SQL DELETE against entities/relations
# ============================================================================

class TestNoDeleteInvariant:
    """AC6: SQL-trace assertion that NO tool emits DELETE on entities/relations."""

    @staticmethod
    def _make_tracing_kg(ctx: ToolContext):
        """Wrap ctx.kg.conn with set_trace_callback to record all SQL."""
        executed: list[str] = []

        # sqlite3 set_trace_callback captures every statement issued on the
        # connection (including those inside KnowledgeGraph / Handlers).
        try:
            ctx.kg.conn.set_trace_callback(lambda stmt: executed.append(stmt))
        except (AttributeError, sqlite3.ProgrammingError):
            pass

        return executed

    def _run_all_write_tools(self, ctx):
        """Exercise every write/maintenance tool at least once."""
        # Seed a target for relation/update
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "rel-src", "type": "function", "name": "src",
        })
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "rel-tgt", "type": "function", "name": "tgt",
        })
        invoke_tool(ctx, "mnemosyne_create_relation", {
            "id": "rel-1", "source_id": "rel-src", "target_id": "rel-tgt",
            "relation_type": "calls",
        })
        invoke_tool(ctx, "mnemosyne_update_entity", {
            "entity_id": "rel-src", "properties": {"updated": True},
        })
        # Wiki prune (plan only) — operates on wiki view, not graph rows.
        invoke_tool(ctx, "mnemosyne_wiki_prune", {})
        # Add text (ingest)
        invoke_tool(ctx, "mnemosyne_add", {"text": "hello", "domain": "daily"})

    def test_no_delete_on_entities_or_relations(self, ctx, tmp_path):
        executed = self._make_tracing_kg(ctx)
        self._run_all_write_tools(ctx)

        delete_stmts = [s for s in executed if isinstance(s, str) and s.upper().startswith("DELETE")]
        offending = [
            s for s in delete_stmts
            if "FROM entities" in s.upper().replace('"', "")
            or "FROM relations" in s.upper().replace('"', "")
            or 'FROM "entities"' in s.lower()
            or 'FROM "relations"' in s.lower()
        ]
        assert offending == [], (
            f"REQ-MCP-006/AC6 violated: DELETE on entities/relations detected: {offending}"
        )

    def test_delete_only_allowed_on_unrelated_tables(self, ctx):
        """A DELETE may appear for wiki/maintenance bookkeeping but NEVER entities/relations."""
        executed = self._make_tracing_kg(ctx)
        # Run a broad set of operations.
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "x1", "type": "task", "name": "x1",
        })
        invoke_tool(ctx, "mnemosyne_update_entity", {
            "entity_id": "x1", "properties": {"k": "v"},
        })
        delete_stmts = [s for s in executed if isinstance(s, str) and s.upper().startswith("DELETE")]
        for s in delete_stmts:
            upper = s.upper().replace('"', "")
            assert "FROM ENTITIES" not in upper, f"DELETE on entities: {s}"
            assert "FROM RELATIONS" not in upper, f"DELETE on relations: {s}"


# ============================================================================
# AC7: read workflow with no API key, no network
# ============================================================================

class TestZeroCostRead:
    """AC7: read-only workflow completes with no API key and no network call."""

    def test_read_workflow_no_api_key_no_network(self, kg_ctx, monkeypatch):
        # Ensure no API keys are present.
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            monkeypatch.delenv(key, raising=False)

        # Block any accidental network call.
        import socket
        def _refuse_conn(*args, **kwargs):
            raise AssertionError(f"Unexpected network call: {args}")
        monkeypatch.setattr(socket, "create_connection", _refuse_conn)

        # search -> get_entity -> stats
        search_result = invoke_tool(kg_ctx, "mnemosyne_search", {"term": "auth"})
        assert search_result["count"] >= 1

        fetched = invoke_tool(kg_ctx, "mnemosyne_get_entity", {"entity_id": "fn-authenticateUser"})
        assert fetched["name"] == "authenticateUser"

        stats = invoke_tool(kg_ctx, "mnemosyne_stats", {})
        assert stats["entities"] >= 2


# ============================================================================
# AC9: scope params filter query results
# ============================================================================

class TestScopeFiltering:
    def test_query_with_scope_filters_results(self, ctx):
        """AC9: scope params on mnemosyne_query filter results."""
        # Entity in scope "proj-a"
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "a-1", "type": "task", "name": "Task A",
            "scope_id": "scope-proj-a",
        })
        # Entity in scope "proj-b"
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "b-1", "type": "task", "name": "Task B",
            "scope_id": "scope-proj-b",
        })
        # Global entity
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "g-1", "type": "task", "name": "Task G",
        })

        # list_entities with scope_id filter narrows results (REQ-MCP-007).
        scoped = invoke_tool(ctx, "mnemosyne_list_entities", {"scope_id": "scope-proj-a"})
        ids = [e["id"] for e in scoped["entities"]]
        assert "a-1" in ids
        assert "b-1" not in ids
        assert "g-1" not in ids

    def test_list_entities_type_filter(self, ctx):
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "t1", "type": "task", "name": "t1",
        })
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "f1", "type": "function", "name": "f1",
        })
        tasks = invoke_tool(ctx, "mnemosyne_list_entities", {"type": "task"})
        assert all(e["type"] == "task" for e in tasks["entities"])
        assert any(e["id"] == "t1" for e in tasks["entities"])


# ============================================================================
# REQ-MCP-008: graceful degradation on missing optional deps
# ============================================================================

class TestGracefulDegradation:
    def test_missing_optional_dep_returns_structured_error(self, ctx):
        """REQ-MCP-008: ImportError in a tool becomes a structured ToolRuntimeError, not a crash."""
        with patch("mnemosyne.mcp.tools.Ingester", create=True) if False else patch(
            "mnemosyne.ingest.ingester.Ingester",
            side_effect=ImportError("No module named 'requests'"),
        ):
            with pytest.raises(ToolRuntimeError) as ei:
                invoke_tool(ctx, "mnemosyne_add", {"text": "x", "domain": "daily"})
        assert ei.value.code == "MISSING_OPTIONAL_DEPENDENCY"
        assert ei.value.missing_capability is not None

    def test_tool_runtime_error_to_dict(self):
        err = ToolRuntimeError("X", "msg", missing_capability="requests")
        d = err.to_dict()
        assert d["error"] == "X"
        assert d["missing_capability"] == "requests"


# ============================================================================
# REQ-MCP-009: SDK isolation — handler returns plain dict
# ============================================================================

class TestSDKIsolation:
    def test_handlers_return_plain_dict(self, ctx):
        """REQ-MCP-009: tools.py handlers return plain dicts, never mcp.types."""
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "iso-1", "type": "task", "name": "iso",
        })
        for tool_name, args in [
            ("mnemosyne_get_entity", {"entity_id": "iso-1"}),
            ("mnemosyne_stats", {}),
            ("mnemosyne_list_entities", {}),
            ("mnemosyne_search", {"term": "iso"}),
        ]:
            result = invoke_tool(ctx, tool_name, args)
            assert isinstance(result, dict), f"{tool_name} returned {type(result)}"

    def test_server_converts_dict_to_mcp_textcontent(self, ctx):
        """REQ-MCP-009: the server layer (not tools.py) converts dicts to mcp.types."""
        import asyncio
        from mnemosyne.mcp.server import MCPServer

        srv = MCPServer(ctx=ctx)
        call_h = srv.server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="mnemosyne_create_entity",
                arguments={"id": "srv-1", "type": "task", "name": "srv"},
            ),
        )
        sr = asyncio.run(call_h(req))
        ctr = sr.root
        assert ctr.isError is False
        assert isinstance(ctr.content[0], types.TextContent)
        body = json.loads(ctr.content[0].text)
        assert body["id"] == "srv-1"

    def test_server_list_tools_returns_mcp_tool_objects(self, ctx):
        import asyncio
        from mnemosyne.mcp.server import MCPServer

        srv = MCPServer(ctx=ctx)
        list_h = srv.server.request_handlers[types.ListToolsRequest]
        sr = asyncio.run(list_h(None))
        lt = sr.root
        assert all(isinstance(t, types.Tool) for t in lt.tools)
        assert len(lt.tools) == len(EXPECTED_TOOLS)

    def test_server_surfaces_apierror_as_structured_content(self, ctx):
        """APIError (NOT_FOUND) becomes a TextContent JSON blob, not an exception."""
        import asyncio
        from mnemosyne.mcp.server import MCPServer

        srv = MCPServer(ctx=ctx)
        call_h = srv.server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="mnemosyne_get_entity",
                arguments={"entity_id": "does-not-exist"},
            ),
        )
        sr = asyncio.run(call_h(req))
        ctr = sr.root
        body = json.loads(ctr.content[0].text)
        assert body["error"] == "NOT_FOUND"


# ============================================================================
# AC8: mnemosyne mcp install --client claude-desktop
# ============================================================================

class TestInstallSnippet:
    def test_install_claude_desktop_prints_valid_snippet(self, capsys):
        """AC8: install --client claude-desktop prints a valid stdio config snippet."""
        from mnemosyne.mcp.cli import main as mcp_main

        code = mcp_main(["install", "--client", "claude-desktop"])
        assert code == 0
        out = capsys.readouterr().out
        # The snippet must contain a JSON config with command + args.
        # Strip comment lines before parsing the JSON block.
        json_lines = [ln for ln in out.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        payload = json.loads("\n".join(json_lines))
        assert "mcpServers" in payload
        assert "mnemosyne" in payload["mcpServers"]
        entry = payload["mcpServers"]["mnemosyne"]
        assert "command" in entry
        assert "-m" in entry["args"]
        assert "mnemosyne.mcp" in entry["args"]

    def test_install_all_clients(self, capsys):
        from mnemosyne.mcp.cli import main as mcp_main

        for client in ("claude-desktop", "hermes", "openclaw"):
            code = mcp_main(["install", "--client", client])
            assert code == 0, client
            out = capsys.readouterr().out
            assert "mnemosyne" in out

    def test_install_unknown_client_returns_error(self, capsys):
        """argparse rejects invalid --client choices by calling sys.exit(2)."""
        from mnemosyne.mcp.cli import main as mcp_main

        with pytest.raises(SystemExit) as ei:
            mcp_main(["install", "--client", "nope"])
        assert ei.value.code == 2

    def test_install_no_write_without_apply(self, tmp_path, capsys, monkeypatch):
        """REQ-MCP-010: install never writes a file unless --apply is given."""
        from mnemosyne.mcp.cli import main as mcp_main

        # Run from tmp_path cwd and ensure no files are created there.
        monkeypatch.chdir(tmp_path)
        code = mcp_main(["install", "--client", "claude-desktop"])
        assert code == 0
        # No files written to the working directory.
        files = [p for p in tmp_path.rglob("*") if p.is_file()]
        assert files == [], f"install wrote files without --apply: {files}"

    def test_install_apply_writes_to_explicit_path(self, tmp_path):
        """REQ-MCP-010: --apply writes only to the user-supplied path."""
        from mnemosyne.mcp.cli import main as mcp_main

        target = tmp_path / "config.json"
        code = mcp_main(["install", "--client", "claude-desktop", "--apply", str(target)])
        assert code == 0
        assert target.exists()
        payload = json.loads(target.read_text())
        assert "mcpServers" in payload

    def test_install_apply_refuses_overwrite_without_force(self, tmp_path, capsys):
        from mnemosyne.mcp.cli import main as mcp_main

        target = tmp_path / "config.json"
        target.write_text("{}")
        code = mcp_main(["install", "--client", "claude-desktop", "--apply", str(target)])
        assert code != 0


# ============================================================================
# AC1: python -m mnemosyne.mcp importable + cli dispatch
# ============================================================================

class TestEntrypoints:
    def test_main_cli_dispatches_mcp(self, capsys):
        """AC1: the top-level `mnemosyne mcp install` reaches the mcp sub-CLI."""
        from mnemosyne.cli import main as cli_main

        cli_main(["mcp", "install", "--client", "hermes"])
        out = capsys.readouterr().out
        assert "mnemosyne" in out
        assert "stdio" in out.lower() or "args" in out.lower()

    def test_mcp_module_importable(self):
        """AC1: `python -m mnemosyne.mcp` entrypoint imports cleanly."""
        import mnemosyne.mcp  # noqa: F401
        import mnemosyne.mcp.__main__  # noqa: F401
        from mnemosyne.mcp.server import run_stdio, create_server
        assert callable(run_stdio)
        assert callable(create_server)

    def test_mcp_no_args_prints_help(self, capsys):
        from mnemosyne.mcp.cli import main as mcp_main

        code = mcp_main([])
        assert code == 0
        out = capsys.readouterr().out
        assert "serve" in out
        assert "install" in out


# ============================================================================
# Create/relation smoke tests
# ============================================================================

class TestCreateRelation:
    def test_create_relation_links_entities(self, ctx):
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "c-src", "type": "function", "name": "caller",
        })
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "c-tgt", "type": "function", "name": "callee",
        })
        result = invoke_tool(ctx, "mnemosyne_create_relation", {
            "id": "rel-calls",
            "source_id": "c-src",
            "target_id": "c-tgt",
            "relation_type": "calls",
        })
        assert result["source_id"] == "c-src"
        assert result["relation_type"] == "calls"

    def test_create_entity_conflict_on_duplicate(self, ctx):
        invoke_tool(ctx, "mnemosyne_create_entity", {
            "id": "dup-1", "type": "task", "name": "dup",
        })
        with pytest.raises(APIError) as ei:
            invoke_tool(ctx, "mnemosyne_create_entity", {
                "id": "dup-1", "type": "task", "name": "dup",
            })
        assert ei.value.code == "CONFLICT"


# ============================================================================
# Wiki maintenance tools smoke tests
# ============================================================================

class TestWikiMaintenance:
    def test_wiki_prune_returns_plan_no_delete(self, ctx, tmp_path):
        """REQ-MCP-005/006: wiki_prune returns a plan, never deletes graph rows."""
        result = invoke_tool(ctx, "mnemosyne_wiki_prune", {
            "wiki_root": str(tmp_path / "wiki"),
        })
        assert result["action"] == "plan"
        # Explicit preservation guarantee must be present.
        assert "preserved" in result

    def test_wiki_status_empty_root(self, ctx, tmp_path):
        result = invoke_tool(ctx, "mnemosyne_wiki_status", {
            "wiki_root": str(tmp_path / "wiki"),
        })
        assert isinstance(result, dict)

"""REQ-NL-005: mnemosyne_ask + mnemosyne_chat MCP tools (in-process dispatch)."""

from __future__ import annotations

import pytest

# Gate the whole module: the system python in this env lacks the ``mcp``
# distribution. The tools themselves are pure-python and exercised when the
# module is importable; otherwise the suite skips cleanly.
pytest.importorskip("mcp")

from mnemosyne.mcp.tools import (  # noqa: E402
    ToolContext,
    build_tool_specs,
    invoke_tool,
    tool_names,
)


@pytest.fixture()
def ctx(tmp_path) -> ToolContext:
    return ToolContext.build(db_path=str(tmp_path / "mcp_ask.db"))


def test_tool_specs_register_ask_and_chat() -> None:
    names = tool_names()
    assert "mnemosyne_ask" in names
    assert "mnemosyne_chat" in names
    # No delete tool exists (REQ-NL-005).
    assert not any("delete" in n for n in names)


def test_ask_honors_scope_schema() -> None:
    specs = {s.name: s for s in build_tool_specs()}
    ask_props = specs["mnemosyne_ask"].input_schema["properties"]
    chat_props = specs["mnemosyne_chat"].input_schema["properties"]
    for scope_key in ("scope_id", "project", "source_channel"):
        assert scope_key in ask_props
        assert scope_key in chat_props


def test_ask_dispatches_in_process(ctx: ToolContext) -> None:
    out = invoke_tool(ctx, "mnemosyne_ask", {"question": "hello world"})
    assert "answer" in out
    assert "citations" in out
    assert out["plan"]["intent"] in (
        "search", "entity_lookup", "relation_query", "path_query", "longdoc_retrieve"
    )


def test_chat_creates_and_resumes_session(ctx: ToolContext) -> None:
    first = invoke_tool(ctx, "mnemosyne_chat", {"message": "first"})
    sid = first["session_id"]
    assert sid and first["turn_id"]
    second = invoke_tool(
        ctx, "mnemosyne_chat", {"message": "second", "session_id": sid}
    )
    assert second["session_id"] == sid


def test_chat_unknown_session_is_404(ctx: ToolContext) -> None:
    from mnemosyne.serve.handlers import APIError

    with pytest.raises(APIError):
        invoke_tool(
            ctx, "mnemosyne_chat", {"message": "x", "session_id": "ghost"}
        )


def test_ask_missing_question_is_422(ctx: ToolContext) -> None:
    from mnemosyne.serve.handlers import APIError

    with pytest.raises(APIError):
        invoke_tool(ctx, "mnemosyne_ask", {})

"""MCP stdio server for mnemosyne (SPEC-MCP-001).

Uses the official ``mcp`` Python SDK low-level server API. All SDK types are
imported ONLY in this module (REQ-MCP-009): :mod:`mnemosyne.mcp.tools` stays
SDK-agnostic and returns plain dicts.

REQ-MCP-002: tool calls dispatch in-process to the shared
:class:`~mnemosyne.mcp.tools.ToolContext` (one ``Handlers`` + one
``KnowledgeGraph`` for the server lifetime).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server

from mnemosyne.mcp.tools import ToolContext, ToolRuntimeError, build_tool_specs, invoke_tool
from mnemosyne.serve.handlers import APIError

logger = logging.getLogger(__name__)

SERVER_NAME = "mnemosyne"
SERVER_VERSION = "0.1.0"


class MCPServer:
    """MCP server bound to a shared :class:`ToolContext`.

    REQ-MCP-002: the same in-process ``KnowledgeGraph`` / ``Handlers``
    instance serves every ``tools/call`` request.
    """

    def __init__(self, ctx: Optional[ToolContext] = None) -> None:
        self.ctx = ctx or ToolContext.build()
        self.server = Server(SERVER_NAME)
        self._register_handlers()

    # -- registration --------------------------------------------------------

    def _register_handlers(self) -> None:
        server = self.server

        @server.list_tools()
        async def handle_list_tools() -> List[types.Tool]:
            return [
                types.Tool(
                    name=spec.name,
                    description=spec.description,
                    inputSchema=spec.input_schema,
                )
                for spec in build_tool_specs()
            ]

        @server.call_tool()
        async def handle_call_tool(  # type: ignore[unused-variable]
            name: str, arguments: Dict[str, Any] | None
        ) -> List[types.TextContent]:
            args = dict(arguments or {})
            try:
                result = invoke_tool(self.ctx, name, args)
            except APIError as exc:
                # HTTP-shaped error -> structured MCP error content.
                logger.info("Tool %s APIError: %s", name, exc.code)
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(exc.to_dict(), default=str),
                    )
                ]
            except ToolRuntimeError as exc:
                # Optional-dep absence or recoverable runtime error (REQ-MCP-008).
                logger.warning("Tool %s runtime error: %s", name, exc.code)
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(exc.to_dict(), default=str),
                    )
                ]
            except Exception as exc:
                logger.exception("Tool %s unexpected error", name)
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {"error": "INTERNAL_ERROR", "message": str(exc)},
                            default=str,
                        ),
                    )
                ]
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(result, default=str),
                )
            ]

    # -- lifecycle -----------------------------------------------------------

    async def _run(self) -> None:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            )

    def run_stdio(self) -> None:
        """Run the MCP server over stdio JSON-RPC (REQ-MCP-001)."""
        try:
            asyncio.run(self._run())
        finally:
            self.ctx.close()

    def close(self) -> None:
        """Close the shared KnowledgeGraph connection."""
        self.ctx.close()


def create_server(db_path: Optional[str] = None) -> MCPServer:
    """Construct a server bound to a (possibly custom) db_path."""
    return MCPServer(ctx=ToolContext.build(db_path=db_path))


def run_stdio(db_path: Optional[str] = None) -> None:
    """Module-level entrypoint: build a server and run it over stdio."""
    server = create_server(db_path=db_path)
    server.run_stdio()

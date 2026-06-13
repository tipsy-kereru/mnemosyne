"""MCP server for mnemosyne (SPEC-MCP-001).

Exposes the knowledge graph as an MCP tool set over stdio JSON-RPC using
direct in-process calls to :class:`~mnemosyne.graph.knowledge_graph.KnowledgeGraph`
and :class:`~mnemosyne.serve.handlers.Handlers`.
"""

from mnemosyne.mcp.server import MCPServer, create_server, run_stdio

__all__ = ["MCPServer", "create_server", "run_stdio"]

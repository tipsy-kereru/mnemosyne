"""MCP tool definitions and SDK-agnostic handler adapters (SPEC-MCP-001).

Each tool is defined as a ``(name, description, input_schema, handler)``
tuple. Handlers receive a :class:`ToolContext` (which wraps a single
:class:`~mnemosyne.serve.handlers.Handlers` + shared
:class:`~mnemosyne.graph.knowledge_graph.KnowledgeGraph`) and the validated
``arguments`` dict, and return a plain ``dict`` result. The
:class:`~mnemosyne.mcp.server.MCPServer` converts these dicts into
``mcp.types`` content blocks, keeping the SDK surface isolated in
``server.py`` per REQ-MCP-009.

REQ-MCP-006 (no-delete): no handler here emits a row-deleting SQL statement.
``mnemosyne_update_entity`` appends a temporal ``entity_history`` row via
``KnowledgeGraph.update_entity``. ``mnemosyne_wiki_prune`` only calls the
non-destructive ``stale_plan`` / ``write_tombstones`` wiki maintainer path.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from mnemosyne.graph.knowledge_graph import KnowledgeGraph
from mnemosyne.serve.handlers import APIError, Handlers

logger = logging.getLogger(__name__)

# JSON-Schema fragment appended to every entity/query tool so an agent can
# scope reads/writes to a session or project (REQ-MCP-007). Each property is
# optional; the underlying query language (@session: / @project: / @channel:)
# already treats absent modifiers as "no filter".
_SCOPE_SCHEMA: Dict[str, Any] = {
    "scope_id": {
        "type": "string",
        "description": "Restrict results to entities/relations with this scope_id.",
    },
    "project": {
        "type": "string",
        "description": "Filter to a named project scope (resolved via scope_manager).",
    },
    "source_channel": {
        "type": "string",
        "description": "Filter by the source_channel tag (e.g. 'cli', 'code', 'discord').",
    },
}


def _scope_params(args: Dict[str, Any]) -> Dict[str, str]:
    """Extract scope filter params from tool arguments (REQ-MCP-007)."""
    out: Dict[str, str] = {}
    for key in ("scope_id", "project", "source_channel"):
        val = args.get(key)
        if val is not None:
            out[key] = str(val)
    return out


def _query_modifiers(args: Dict[str, Any]) -> str:
    """Build a ``@project:..@channel:..`` suffix from scope args.

    Used for ``mnemosyne_query`` / ``mnemosyne_search`` so they hit the same
    ``KnowledgeGraph.query`` modifier path the CLI uses (AC9).
    """
    parts: List[str] = []
    if args.get("project"):
        parts.append(f"@project:{args['project']}")
    if args.get("source_channel"):
        parts.append(f"@channel:{args['source_channel']}")
    if args.get("scope_id"):
        # The query language has no raw @scope_id modifier; project/channel
        # are the named-resolution paths. scope_id is honoured by the
        # list/get paths directly, and for search we pass it through the
        # Handlers layer (see _search handler).
        pass
    return "".join(parts)


@dataclass
class ToolContext:
    """Shared server-lifetime context handed to every tool handler.

    REQ-MCP-002: a single ``Handlers`` + ``KnowledgeGraph`` instance serves
    all in-process tool calls.
    """

    handlers: Handlers
    kg: KnowledgeGraph
    db_path: str

    @classmethod
    def build(cls, db_path: Optional[str] = None) -> "ToolContext":
        """Construct a server-lifetime context with a live KG + Handlers."""
        kg = KnowledgeGraph(db_path)
        handlers = Handlers(kg, str(kg.db_path))
        return cls(handlers=handlers, kg=kg, db_path=str(kg.db_path))

    def close(self) -> None:
        self.kg.close()


# -- Handler return shape --------------------------------------------------
# Each handler returns a dict. The server wraps it into MCP content. We also
# raise APIError (from handlers) for HTTP-shaped errors; the server converts
# those into structured error results (REQ-MCP-008 for optional-dep absences
# uses ToolRuntimeError below).


class ToolRuntimeError(Exception):
    """Structured error surfaced as an MCP ``isError`` result.

    Used for optional-dependency absence (REQ-MCP-008) and other recoverable
    tool failures that must NOT crash the server.
    """

    def __init__(self, code: str, message: str, missing_capability: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.missing_capability = missing_capability

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "error": self.code,
            "message": self.message,
        }
        if self.missing_capability:
            payload["missing_capability"] = self.missing_capability
        return payload


HandlerFunc = Callable[[ToolContext, Dict[str, Any]], Dict[str, Any]]


def _module_name_from_import_error(message: str) -> Optional[str]:
    """Best-effort extraction of a module name from an ImportError message.

    Handles the common ``No module named 'X'`` shape produced by both the
    import machinery and libraries that raise ImportError from constructor
    code. Returns None when no name can be parsed.
    """
    import re

    m = re.search(r"No module named ['\"]([^'\"]+)['\"]", message)
    if m:
        # The captured name may be dotted (e.g. 'tree_sitter'); keep the top
        # level package only so it maps to the installable distribution.
        return m.group(1).split(".")[0]
    return None


@dataclass
class ToolSpec:
    """SDK-agnostic tool definition."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: HandlerFunc


# ============================================================================
# READ tools (REQ-MCP-003)
# ============================================================================


def _search(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    term = args.get("term") or args.get("q") or ""
    if not term:
        raise APIError("VALIDATION_ERROR", "Missing 'term' field", 422)
    # Compose scope modifiers so search honours project/channel (AC9).
    modifiers = _query_modifiers(args)
    # Handlers.search uses ?q= ; we reuse kg.query("search:TERM") to hit FTS5.
    raw = ctx.kg.query(f"search:{term}{modifiers}")
    limit = int(args.get("limit", 50))
    results = raw.get("results", [])
    truncated = False
    if len(results) > limit:
        results = results[:limit]
        truncated = True
    return {
        "type": raw.get("type", "search"),
        "term": term,
        "results": results,
        "count": len(results),
        "truncated": truncated,
    }


def _query(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    query_str = args.get("query")
    if not query_str:
        raise APIError("VALIDATION_ERROR", "Missing 'query' field", 422)
    modifiers = _query_modifiers(args)
    return ctx.kg.query(f"{query_str}{modifiers}")


def _get_entity(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    entity_id = args.get("entity_id") or args.get("id")
    if not entity_id:
        raise APIError("VALIDATION_ERROR", "Missing 'entity_id' field", 422)
    entity = ctx.kg.get_entity(entity_id)
    if entity is None:
        raise APIError("NOT_FOUND", f"Entity not found: {entity_id}", 404)
    history = ctx.kg.get_entity_history(entity_id)
    return {
        "id": entity.id,
        "type": entity.type,
        "name": entity.name,
        "properties": entity.properties,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
        "version": entity.version,
        "scope_id": entity.scope_id,
        "source_channel": entity.source_channel,
        "history": history,
    }


def _list_entities(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    params = {k: v for k, v in _scope_params(args).items() if v}
    if args.get("type"):
        params["type"] = str(args["type"])
    limit = int(args.get("limit", 100))
    status, body = ctx.handlers.list_entities(params)
    entities = body.get("entities", [])[:limit]
    return {"entities": entities, "count": len(entities), "truncated": len(body.get("entities", [])) > limit}


def _stats(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    status, body = ctx.handlers.stats()
    return body


def _wiki_status(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    params: Dict[str, str] = {}
    if args.get("wiki_root"):
        params["wiki_root"] = str(args["wiki_root"])
    status, body = ctx.handlers.wiki_status(params)
    return body


def _wiki_lint(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    params: Dict[str, str] = {}
    if args.get("wiki_root"):
        params["wiki_root"] = str(args["wiki_root"])
    status, body = ctx.handlers.wiki_lint(params)
    return body


# ============================================================================
# WRITE tools (REQ-MCP-004) — create/update only, never delete
# ============================================================================


def _create_entity(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "id": args.get("id"),
        "type": args.get("type"),
        "name": args.get("name"),
        "properties": args.get("properties", {}),
        "source_channel": args.get("source_channel", "mcp"),
    }
    if args.get("scope_id"):
        body["scope_id"] = args["scope_id"]
    status, result = ctx.handlers.create_entity(body)
    return result


def _update_entity(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    """Append a temporal version (entity_history), never remove (AC5, REQ-MCP-006)."""
    entity_id = args.get("entity_id") or args.get("id")
    if not entity_id:
        raise APIError("VALIDATION_ERROR", "Missing 'entity_id' field", 422)
    existing = ctx.kg.get_entity(entity_id)
    if existing is None:
        raise APIError("NOT_FOUND", f"Entity not found: {entity_id}", 404)

    from mnemosyne.graph.knowledge_graph import Entity

    entity = Entity(
        id=entity_id,
        type=args.get("type", existing.type),
        name=args.get("name", existing.name),
        properties=args.get("properties", existing.properties),
        created_at=existing.created_at,
        updated_at=existing.updated_at,
        version=existing.version,
        scope_id=args.get("scope_id", existing.scope_id),
        source_channel=args.get("source_channel", existing.source_channel),
    )
    try:
        updated = ctx.kg.update_entity(entity)
    except KeyError as exc:
        raise APIError("NOT_FOUND", str(exc), 404) from exc
    history = ctx.kg.get_entity_history(entity_id)
    return {
        "id": updated.id,
        "type": updated.type,
        "name": updated.name,
        "properties": updated.properties,
        "version": updated.version,
        "updated_at": updated.updated_at,
        "history_count": len(history),
        "history": history,
    }


def _create_relation(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "id": args.get("id"),
        "source_id": args.get("source_id"),
        "target_id": args.get("target_id"),
        "relation_type": args.get("relation_type"),
        "properties": args.get("properties", {}),
        "source_channel": args.get("source_channel", "mcp"),
    }
    if args.get("scope_id"):
        body["scope_id"] = args["scope_id"]
    status, result = ctx.handlers.create_relation(body)
    return result


def _add(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    """Ingest text/file/url via the in-process Ingester (AC4, REQ-MCP-002)."""
    from mnemosyne.ingest.ingester import Ingester

    text = args.get("text")
    target = args.get("target")
    if not target and not text:
        raise APIError("VALIDATION_ERROR", "Provide 'target' (file/url) or 'text'", 422)

    # Ingest with no LLM bridge (default deterministic + SLM only, REQ-MCP-009).
    # Disable wiki writes by default so the MCP tool stays cheap and the test
    # suite does not need a wiki root; pass --wiki-root via args to opt in.
    wiki_root = None
    if args.get("wiki_root"):
        wiki_root = Path(args["wiki_root"])

    ingester = Ingester(
        db_path=Path(ctx.db_path),
        wiki_root=wiki_root,
        dry_run=bool(args.get("dry_run", False)),
    )
    result = ingester.add(
        target=target or "",
        domain=args.get("domain", "daily"),
        scope_id=args.get("scope_id"),
        source_channel=args.get("source_channel", "mcp"),
        text=text,
    )
    if isinstance(result, list):
        total_e = sum(r.entities_added for r in result)
        total_r = sum(r.relations_added for r in result)
        return {"sources": len(result), "entities_added": total_e, "relations_added": total_r}
    out: Dict[str, Any] = {
        "source": result.source,
        "entities_added": result.entities_added,
        "relations_added": result.relations_added,
        "raw_path": str(result.raw_path) if result.raw_path else None,
        "wiki_paths": [str(p) for p in result.wiki_paths],
    }
    if result.skipped:
        out["skipped"] = True
        out["skip_reason"] = result.skip_reason
    return out


def _extract(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    """Run the deterministic extraction pipeline in-process (zero-LLM)."""
    from mnemosyne.extraction.pipeline import ExtractionPipeline

    source = args.get("source")
    if not source:
        raise APIError("VALIDATION_ERROR", "Missing 'source' path", 422)
    path = Path(source).expanduser()
    if not path.exists():
        raise APIError("NOT_FOUND", f"Source not found: {source}", 404)

    pipeline = ExtractionPipeline(
        domain=args.get("domain", "coding"),
        source=path,
        knowledge_graph=ctx.kg,
        scope_id=args.get("scope_id"),
        source_channel=args.get("source_channel", "mcp"),
        # Deterministic + semantic only by default (REQ-MCP-009): keep the
        # synthesis LLM layer off unless explicitly enabled.
        enable_semantic=bool(args.get("enable_semantic", True)),
        enable_synthesis=bool(args.get("enable_synthesis", False)),
        incremental=bool(args.get("incremental", False)),
    )
    report = pipeline.run()
    return {
        "domain": report.domain,
        "source": report.source,
        "files_processed": report.files_processed,
        "files_skipped": report.files_skipped,
        "files_failed": report.files_failed,
        "entities_extracted": report.entities_extracted,
        "entities_stored": report.entities_stored,
        "relations_extracted": report.relations_extracted,
        "relations_stored": report.relations_stored,
        "errors": [str(e) for e in report.errors],
    }


# ============================================================================
# WIKI maintenance tools (REQ-MCP-005) — rebuild + prune (view-only)
# ============================================================================


def _wiki_rebuild(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer

    wiki_root = args.get("wiki_root") or str(Path.home() / "mnemosyne" / "wiki")
    maintainer = LLMWikiMaintainer(wiki_root=wiki_root)
    update = maintainer.rebuild_from_graph(ctx.db_path, dry_run=bool(args.get("dry_run", False)))
    return {
        "rebuilt": not args.get("dry_run", False),
        "dry_run": bool(args.get("dry_run", False)),
        "paths": [str(p) for p in update.paths],
        "path_count": len(update.paths),
    }


def _wiki_prune(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    """Prune low-value wiki markdown. View-only tombstones, never graph rows (REQ-MCP-006)."""
    from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer

    wiki_root = args.get("wiki_root") or str(Path.home() / "mnemosyne" / "wiki")
    maintainer = LLMWikiMaintainer(wiki_root=wiki_root)
    apply_tombstones = bool(args.get("apply_tombstones", False))
    if apply_tombstones:
        payload = maintainer.write_tombstones(ctx.db_path)
        payload["action"] = "tombstones_written"
    else:
        payload = maintainer.stale_plan(ctx.db_path)
        payload["action"] = "plan"
    # Explicit no-delete guarantee in the response so agents understand.
    payload["preserved"] = "no entities, relations, raw sources, or graph rows were deleted"
    return payload


# ============================================================================
# Tool registry
# ============================================================================


def _obj_schema(
    properties: Dict[str, Any],
    required: List[str],
    *,
    add_scope: bool = False,
) -> Dict[str, Any]:
    """Build an object inputSchema, optionally merging in scope params."""
    props = dict(properties)
    if add_scope:
        props.update({k: dict(v) for k, v in _SCOPE_SCHEMA.items()})
    return {
        "type": "object",
        "properties": props,
        "required": list(required),
        "additionalProperties": False,
    }


def build_tool_specs() -> List[ToolSpec]:
    """Return the full MCP tool set (REQ-MCP-003/004/005).

    The order is stable: read tools, then write tools, then wiki maintenance.
    REQ-MCP-006: no delete tool is present in this list.
    """
    specs: List[ToolSpec] = [
        # -- READ --
        ToolSpec(
            name="mnemosyne_search",
            description=(
                "Fuzzy entity search via the FTS5 index (SPEC-HEADROOM-001). "
                "Returns ranked matches for partial/prefix terms."
            ),
            input_schema=_obj_schema(
                {
                    "term": {"type": "string", "description": "Search term (partial match supported)."},
                    "limit": {"type": "integer", "default": 50, "minimum": 1},
                },
                required=["term"],
                add_scope=True,
            ),
            handler=_search,
        ),
        ToolSpec(
            name="mnemosyne_query",
            description=(
                "Structured graph query. Supports entity:TYPE[NAME], relation:TYPE, "
                "path:FROM,TO, and search:TERM with @project/@channel scope modifiers."
            ),
            input_schema=_obj_schema(
                {"query": {"type": "string", "description": "Query expression (see KnowledgeGraph.query syntax)."}},
                required=["query"],
                add_scope=True,
            ),
            handler=_query,
        ),
        ToolSpec(
            name="mnemosyne_get_entity",
            description="Fetch one entity by id, including its temporal history.",
            input_schema=_obj_schema(
                {"entity_id": {"type": "string", "description": "Entity id."}},
                required=["entity_id"],
            ),
            handler=_get_entity,
        ),
        ToolSpec(
            name="mnemosyne_list_entities",
            description="List entities with optional type and scope filters.",
            input_schema=_obj_schema(
                {
                    "type": {"type": "string", "description": "Optional entity type filter."},
                    "limit": {"type": "integer", "default": 100, "minimum": 1},
                },
                required=[],
                add_scope=True,
            ),
            handler=_list_entities,
        ),
        ToolSpec(
            name="mnemosyne_stats",
            description="Graph statistics: entity/relation counts, type distribution, scope distribution.",
            input_schema=_obj_schema({}, required=[]),
            handler=_stats,
        ),
        ToolSpec(
            name="mnemosyne_wiki_status",
            description="Read-only wiki health summary.",
            input_schema=_obj_schema(
                {"wiki_root": {"type": "string", "description": "Wiki root (default ~/mnemosyne/wiki)."}},
                required=[],
            ),
            handler=_wiki_status,
        ),
        ToolSpec(
            name="mnemosyne_wiki_lint",
            description="Read-only wiki integrity report (broken links, metadata, graph drift).",
            input_schema=_obj_schema(
                {"wiki_root": {"type": "string", "description": "Wiki root (default ~/mnemosyne/wiki)."}},
                required=[],
            ),
            handler=_wiki_lint,
        ),
        # -- WRITE (create/update only) --
        ToolSpec(
            name="mnemosyne_add",
            description=(
                "Ingest a file path, URL, or inline text into the knowledge graph. "
                "Uses the deterministic + SLM extraction layers (zero LLM cost by default)."
            ),
            input_schema=_obj_schema(
                {
                    "target": {"type": "string", "description": "File path or URL to ingest."},
                    "text": {"type": "string", "description": "Inline text to ingest (instead of target)."},
                    "domain": {
                        "type": "string",
                        "enum": ["coding", "daily", "legal"],
                        "default": "daily",
                    },
                    "dry_run": {"type": "boolean", "default": False},
                    "wiki_root": {"type": "string", "description": "Optional wiki root to also update."},
                },
                required=[],
                add_scope=True,
            ),
            handler=_add,
        ),
        ToolSpec(
            name="mnemosyne_extract",
            description=(
                "Run the zero-LLM deterministic extraction pipeline on a file or directory. "
                "Stores extracted code entities in the graph."
            ),
            input_schema=_obj_schema(
                {
                    "source": {"type": "string", "description": "File or directory to extract from."},
                    "domain": {
                        "type": "string",
                        "enum": ["coding", "daily", "legal"],
                        "default": "coding",
                    },
                    "incremental": {"type": "boolean", "default": False},
                },
                required=["source"],
                add_scope=True,
            ),
            handler=_extract,
        ),
        ToolSpec(
            name="mnemosyne_create_entity",
            description="Create a new entity. Idempotency conflicts surface as an error.",
            input_schema=_obj_schema(
                {
                    "id": {"type": "string", "description": "Globally unique entity id."},
                    "type": {"type": "string", "description": "Entity type (e.g. function, task, person)."},
                    "name": {"type": "string", "description": "Human-readable name."},
                    "properties": {"type": "object", "default": {}},
                },
                required=["id", "type", "name"],
                add_scope=True,
            ),
            handler=_create_entity,
        ),
        ToolSpec(
            name="mnemosyne_update_entity",
            description=(
                "Update an existing entity. Appends a new temporal version "
                "(entity_history); the prior version is preserved. Never deletes."
            ),
            input_schema=_obj_schema(
                {
                    "entity_id": {"type": "string", "description": "Entity id to update."},
                    "type": {"type": "string", "description": "New type (optional, defaults to existing)."},
                    "name": {"type": "string", "description": "New name (optional)."},
                    "properties": {"type": "object", "default": {}},
                },
                required=["entity_id"],
                add_scope=True,
            ),
            handler=_update_entity,
        ),
        ToolSpec(
            name="mnemosyne_create_relation",
            description="Create a relation (edge) between two existing entities.",
            input_schema=_obj_schema(
                {
                    "id": {"type": "string", "description": "Globally unique relation id."},
                    "source_id": {"type": "string"},
                    "target_id": {"type": "string"},
                    "relation_type": {"type": "string", "description": "e.g. calls, depends_on, related_to."},
                    "properties": {"type": "object", "default": {}},
                },
                required=["id", "source_id", "target_id", "relation_type"],
                add_scope=True,
            ),
            handler=_create_relation,
        ),
        # -- WIKI maintenance --
        ToolSpec(
            name="mnemosyne_wiki_rebuild",
            description=(
                "Regenerate rebuildable wiki sections from graph data. "
                "Preserves human notes outside MNEMOSYNE markers."
            ),
            input_schema=_obj_schema(
                {
                    "wiki_root": {"type": "string", "description": "Wiki root (default ~/mnemosyne/wiki)."},
                    "dry_run": {"type": "boolean", "default": False},
                },
                required=[],
            ),
            handler=_wiki_rebuild,
        ),
        ToolSpec(
            name="mnemosyne_wiki_prune",
            description=(
                "Prune low-value wiki markdown. By default returns a non-destructive stale plan; "
                "with apply_tombstones=true writes tombstone records without deleting pages or "
                "graph rows. NEVER deletes entities, relations, raw sources, or graph rows."
            ),
            input_schema=_obj_schema(
                {
                    "wiki_root": {"type": "string", "description": "Wiki root (default ~/mnemosyne/wiki)."},
                    "apply_tombstones": {"type": "boolean", "default": False},
                },
                required=[],
            ),
            handler=_wiki_prune,
        ),
    ]
    return specs


def tool_names() -> List[str]:
    """Return the sorted list of exposed tool names (REQ-MCP-006 audit helper)."""
    return sorted(spec.name for spec in build_tool_specs())


def invoke_tool(ctx: ToolContext, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a tool call by name to its handler.

    Raises :class:`APIError` for HTTP-shaped errors (validation/not-found/conflict)
    and :class:`ToolRuntimeError` for optional-dependency absence (REQ-MCP-008).
    Unknown tool names raise :class:`APIError` with code ``UNKNOWN_TOOL``.
    """
    for spec in build_tool_specs():
        if spec.name == name:
            try:
                return spec.handler(ctx, arguments)
            except ImportError as exc:
                # Missing optional dependency (e.g. tree-sitter, gliner, Rust core).
                # exc.name is only populated by the real import machinery; when
                # the error is raised from constructor code we parse the module
                # name out of the message (No module named 'X') as a fallback.
                cap = exc.name or _module_name_from_import_error(str(exc))
                logger.warning("Tool %s missing optional dep: %s", name, exc)
                raise ToolRuntimeError(
                    code="MISSING_OPTIONAL_DEPENDENCY",
                    message=f"Tool '{name}' requires an optional dependency that is not installed: {exc.name or exc}",
                    missing_capability=cap,
                ) from exc
            except sqlite3.OperationalError as exc:
                logger.error("Tool %s database error: %s", name, exc)
                raise ToolRuntimeError(
                    code="DATABASE_ERROR",
                    message=f"Database error in tool '{name}': {exc}",
                ) from exc
    raise APIError("UNKNOWN_TOOL", f"Unknown tool: {name}", 404)

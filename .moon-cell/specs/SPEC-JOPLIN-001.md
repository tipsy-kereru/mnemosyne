# SPEC-JOPLIN-001: External Tool Integration API (mnemosyne serve)

Generated: 2026-05-31 03:14:25 NZST
Status: completed
Priority: high
Risk: medium
Source: Joplin plugin integration requirement — HTTP API for external tool access

## 1. Problem Statement

mnemosyne currently provides only a CLI interface (`mnemosyne add`, `mnemosyne query`, etc.). External tools like the Joplin plugin cannot maintain a persistent connection to the knowledge graph. Each CLI invocation spins up a new Python process, parses arguments, opens SQLite, executes, and exits. This is too slow for real-time features like graph visualization updates, wikilink autocomplete, and backlink queries.

## 2. Goals

- Add `mnemosyne serve` subcommand that starts a local HTTP server
- Expose entity CRUD, relation queries, search, wiki status, and project operations via RESTful JSON API
- Support read-heavy operations with sub-100ms response time
- Support optional authentication for multi-user scenarios (default: localhost-only, no auth)
- Preserve all existing CLI functionality unchanged

## 3. Non-Goals

- WebSocket support (polling is sufficient for initial version)
- Multi-user access control or rate limiting
- Remote network access (localhost only by default)
- Changes to existing CLI commands or their output formats

## 4. Facts

- `KnowledgeGraph` class at `mnemosyne/graph/knowledge_graph.py` has all needed CRUD methods
- SQLite access is synchronous via `sqlite3` module
- Current CLI uses argparse with subcommands
- 507 tests pass, 46 source files
- Python 3.11+ required
- Package uses `uv` for dependency management

## 5. Assumptions

- HTTP server runs on localhost with configurable port (default: 57832)
- Single-process, single-thread (async not needed for localhost-only SQLite)
- JSON request/response bodies
- Server lifecycle managed by the external tool (start/stop)
- No file upload through API — use CLI `mnemosyne add` for ingestion

## 6. Requirements

### REQ-S1-001: HTTP Server Command

Add `mnemosyne serve` subcommand:
- `mnemosyne serve [--host 127.0.0.1] [--port 57832] [--db-path PATH]`
- Starts HTTP server using Python stdlib `http.server` or lightweight framework (e.g., `aiohttp` or `fastapi`)
- Blocks until Ctrl+C or SIGTERM

### REQ-S1-002: Entity CRUD Endpoints

```
GET    /api/v1/entities?type={type}&scope_id={scope_id}    List entities
GET    /api/v1/entities/{id}                                Get entity
POST   /api/v1/entities                                     Create entity
PUT    /api/v1/entities/{id}                                Update entity
DELETE /api/v1/entities/{id}                                Delete entity (soft)
```

### REQ-S1-003: Relation Endpoints

```
GET    /api/v1/relations?source={id}&target={id}&type={type}   List relations
GET    /api/v1/relations/{id}                                   Get relation
POST   /api/v1/relations                                        Create relation
```

### REQ-S1-004: Query Endpoint

```
POST   /api/v1/query    {"query": "entity:function[parse_config]", "format": "json"}
```

Reuses existing `KnowledgeGraph.query()` parser.

### REQ-S1-005: Search Endpoint

```
GET    /api/v1/search?q={text}&limit={n}    Full-text search
```

### REQ-S1-006: Stats and Health

```
GET    /api/v1/stats       Entity/relation counts, DB size
GET    /api/v1/health       {"status": "ok", "version": "0.2.0"}
```

### REQ-S1-007: Project Endpoints

```
GET    /api/v1/projects                   List registered projects
GET    /api/v1/projects/{hash}            Get project details
POST   /api/v1/projects/register          Register project path
```

### REQ-S1-008: Wiki Endpoints

```
GET    /api/v1/wiki/status?wiki_root={path}      Wiki status summary
GET    /api/v1/wiki/lint?wiki_root={path}          Lint warnings
```

### REQ-S1-009: Error Response Format

```json
{"error": "ENTITY_NOT_FOUND", "message": "Entity 'fn:parse' not found", "status": 404}
```

## 7. Acceptance Criteria

| ID | Criterion | Verification |
|---|---|---|
| AC-S1-001 | `mnemosyne serve` starts HTTP server on configured port | `curl http://localhost:57832/api/v1/health` returns 200 |
| AC-S1-002 | Entity CRUD round-trip works via HTTP | Create, read, update, delete via curl |
| AC-S1-003 | Query endpoint returns same results as CLI | Compare `POST /api/v1/query` vs `mnemosyne query` |
| AC-S1-004 | Response time under 100ms for read operations | Benchmark with 1000 entities |
| AC-S1-005 | All existing 507 tests continue to pass | `uv run pytest tests/` |
| AC-S1-006 | Server shuts down cleanly on SIGTERM | Process exits, no orphan connections |

## 8. Risks

| ID | Risk | Mitigation |
|---|---|---|
| RK-S1-001 | SQLite concurrent writes from serve + CLI | Document single-writer constraint; use WAL mode |
| RK-S1-002 | Framework dependency bloat | Use stdlib http.server or minimal dependency |
| RK-S1-003 | Port conflicts | Configurable port with auto-fallback |

## 9. Task Breakdown

| Task | Description | Dependencies |
|---|---|---|
| T1: Framework | Choose HTTP framework, add dependency, scaffold server module | None |
| T2: Entity API | Implement entity CRUD endpoints wrapping KnowledgeGraph methods | T1 |
| T3: Relation API | Implement relation endpoints | T1 |
| T4: Query API | Implement query/search endpoints | T1 |
| T5: Project/Wiki | Implement project and wiki endpoints | T1 |
| T6: CLI Integration | Add `serve` subcommand to cli.py | T1-T5 |
| T7: Tests | Add API integration tests | T1-T6 |

## 10. Files to Create/Modify

| File | Action |
|---|---|
| `mnemosyne/serve/` | NEW — server package directory |
| `mnemosyne/serve/__init__.py` | NEW — package init |
| `mnemosyne/serve/app.py` | NEW — HTTP server and route handlers |
| `mnemosyne/serve/handlers.py` | NEW — request/response handlers |
| `mnemosyne/cli.py` | MODIFY — add `serve` subcommand |
| `tests/test_serve.py` | NEW — API integration tests |
| `pyproject.toml` | MODIFY — add HTTP framework dependency |

# SPEC-JOPLIN-002: Joplin Plugin HTTP Bridge

Generated: 2026-05-31 03:14:25 NZST
Status: completed
Priority: high
Risk: medium
Source: Joplin plugin integration — connect plugin to mnemosyne via HTTP API
Depends on: SPEC-JOPLIN-001 (mnemosyne serve)

## 1. Problem Statement

The Joplin plugin currently stores its knowledge graph in an in-memory `Map<string, Entity>` serialized to Joplin plugin settings JSON. This data is disconnected from mnemosyne's SQLite database. The plugin cannot query relations, perform full-text search, or access wiki layer features. Regex-based entity extraction is rudimentary compared to mnemosyne's tree-sitter and SLM pipelines.

## 2. Goals

- Replace in-memory Map with HTTP calls to `mnemosyne serve`
- Expose full mnemosyne query capabilities from within Joplin
- Manage mnemosyne server lifecycle (start/stop) from the plugin
- Cache responses for responsive UI
- Graceful degradation when mnemosyne server is unavailable

## 3. Non-Goals

- Direct SQLite access from Joplin plugin
- Running mnemosyne extraction pipeline inside Joplin
- Modifying mnemosyne server behavior from the plugin

## 4. Facts

- Joplin desktop plugins run in Node.js sandbox with `child_process` and `net` access
- Current plugin: `joplin-plugin/knowledge-graph/src/index.ts` (~600 LOC)
- `fetch` API available in Node.js 18+
- mnemosyne serve API (SPEC-JOPLIN-001) provides JSON endpoints on localhost

## 5. Assumptions

- mnemosyne serve is started automatically by the plugin or manually by user
- Default port 57832, configurable in plugin settings
- HTTP round-trip latency acceptable for read operations (<100ms target)
- Plugin settings store mnemosyne DB path and server port

## 6. Requirements

### REQ-S2-001: Server Lifecycle Management

Add server management to plugin:
- `mnemosyneServe.start()` — spawn `mnemosyne serve` as child process
- `mnemosyneServe.stop()` — send SIGTERM to child process
- `mnemosyneServe.isRunning()` — health check via `GET /api/v1/health`
- Auto-start on plugin initialization (configurable in settings)
- Auto-restart on crash with exponential backoff

### REQ-S2-002: API Client Module

Create `src/mnemosyne_client.ts`:
- `MnemosyneClient` class with base URL configuration
- `getEntities(type?, scopeId?)` — list entities
- `getEntity(id)` — get single entity
- `searchEntities(query)` — full-text search
- `queryGraph(queryStr)` — structured graph query
- `getRelations(sourceId?, targetId?, type?)` — list relations
- `getBacklinks(entityId)` — get all relations targeting entity
- `getStats()` — graph statistics
- All methods return typed Promise responses

### REQ-S2-003: Data Layer Replacement

Replace `graphDB: Map<string, Entity>` with `MnemosyneClient` calls:
- `extractEntitiesFromNote()` → POST to mnemosyne serve (or keep local regex + sync)
- `searchKnowledgeGraph()` → `client.searchEntities()`
- `loadKnowledgeGraph()` → `client.getEntities()` with local cache
- `saveKnowledgeGraph()` → remove (mnemosyne DB is source of truth)

### REQ-S2-004: Response Caching

Implement in-memory LRU cache:
- Cache entity lookups for 30 seconds
- Cache search results for 10 seconds
- Invalidate on note save events
- Max cache size: 500 entries

### REQ-S2-005: Graceful Degradation

When mnemosyne serve is unavailable:
- Show "mnemosyne disconnected" status in plugin UI
- Fall back to local regex extraction (current behavior)
- Display cached data when available
- Auto-reconnect when server becomes available

### REQ-S2-006: Plugin Settings

Add settings panel:
- mnemosyne DB path (default: `~/mnemosyne/graph/knowledge.db`)
- Server port (default: 57832)
- Auto-start server (default: true)
- Connection status indicator

## 7. Acceptance Criteria

| ID | Criterion | Verification |
|---|---|---|
| AC-S2-001 | Plugin can start/stop mnemosyne serve | Plugin settings toggle, process appears/disappears |
| AC-S2-002 | Entity search returns results from mnemosyne DB | Search dialog shows real DB entities |
| AC-S2-003 | Backlinks query works | Click entity → see incoming relations |
| AC-S2-004 | Graceful degradation when server is down | Plugin shows offline status, falls back to local |
| AC-S2-005 | Cache improves repeated query latency | Second query returns from cache |

## 8. Risks

| ID | Risk | Mitigation |
|---|---|---|
| RK-S2-001 | mnemosyne serve not installed/accessible | Detect absence, show install instructions |
| RK-S2-002 | HTTP latency too slow for autocomplete | Cache + debounce + prefetch |
| RK-S2-003 | Process management across platforms | Test macOS primarily, document Linux/Windows |

## 9. Task Breakdown

| Task | Description | Dependencies |
|---|---|---|
| T1: Client | Create `MnemosyneClient` HTTP client module | SPEC-JOPLIN-001 |
| T2: Lifecycle | Implement server start/stop/health management | T1 |
| T3: Replace | Replace Map with client calls in existing plugin code | T1 |
| T4: Cache | Implement LRU response cache | T1 |
| T5: Settings | Add plugin settings panel | T1 |
| T6: Degradation | Implement graceful offline fallback | T3 |
| T7: Tests | Add integration tests with mock HTTP server | T1-T6 |

## 10. Files to Create/Modify

| File | Action |
|---|---|
| `joplin-plugin/knowledge-graph/src/mnemosyne_client.ts` | NEW — HTTP API client |
| `joplin-plugin/knowledge-graph/src/server_manager.ts` | NEW — process lifecycle |
| `joplin-plugin/knowledge-graph/src/cache.ts` | NEW — LRU cache |
| `joplin-plugin/knowledge-graph/src/index.ts` | MODIFY — replace Map with client |
| `joplin-plugin/knowledge-graph/src/settings.ts` | NEW — plugin settings |

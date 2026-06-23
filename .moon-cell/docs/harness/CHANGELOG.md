# Moon Cell Harness Changelog

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-06-20 22:50:19 NZST

## [0.4.0] - 2026-06-20

### Planned
- SPEC-LONGDOC-001: PageIndex-style self-contained long-document tree indexing
  (vectorless, SLM-first + LLM-fallback, no-delete supersession).
- SPEC-NLQUERY-001: Natural-language query + multi-turn chat layer over the
  knowledge graph (HTTP `/ask` `/chat` + MCP `mnemosyne_ask` `mnemosyne_chat`).
- Laplace integration: both SPECs converted to `.harness/issues/ISSUE-0001.md`
  (LONGDOC, high risk, mandatory security phase) and `ISSUE-0002.md` (NLQUERY,
  medium risk). Awaiting human `/laplace:approve` before dev runs.

### Source
- Architecture audit: mnemosyne vs OpenKB comparison (2026-06-20 session).
- Gap: mnemosyne lacks long-doc retrieval and NL query; OpenKB ships both but
  via external `pageindex` dep and LLM-required compilation. mnemosyne path =
  self-contained, zero-new-dependency, SLM-first.

### Design Decisions
- DEC-013: Self-contained tree indexer (B) over external `pageindex` dep (A) —
  preserves zero-external-dependency principle.
- DEC-014: SLM-first (GLiNER2) + LLM-fallback (LLMBridge) for both indexer and
  answer synthesis — consistent with mnemosyne's 3-layer extraction model.
- DEC-015: HTTP + MCP dual exposure for NL query — reuses `mnemosyne serve`
  for Joplin plugin and MCP for agent integration.
- DEC-016: No-delete supersession for document trees (status flip, no DELETE)
  — matches SPEC-MCP-001 contract; chat sessions same pattern.

## [0.3.0] - 2026-05-31

### Planned
- SPEC-JOPLIN-001: External Tool Integration API (`mnemosyne serve` HTTP server).
- SPEC-JOPLIN-002: Joplin Plugin HTTP Bridge (replace in-memory Map with mnemosyne API client).
- SPEC-JOPLIN-003: Real-Time Graph Visualization (D3.js force-directed graph, backlinks, autocomplete).
- SPEC-JOPLIN-004: Edit-to-Graph Real-Time Sync (onContentChange pipeline, 2s graph updates).

### Completed
- SPEC-JOPLIN-001: mnemosyne serve HTTP API. 15 endpoints, 19 tests, zero external deps.
- Files: mnemosyne/serve/{__init__,app,handlers}.py, tests/test_serve.py, mnemosyne/cli.py modified.
- Merged to main: commit 7d2633f.

### Evidence
- `uv run pytest tests/ -q` → 526 passed (507 existing + 19 new).
- `ruff check mnemosyne tests` → All checks passed.
- E2E smoke: health → 200, stats → 3033 entities, SIGTERM → clean shutdown.
- SPEC-JOPLIN-003: Real-Time Graph Visualization (D3.js force-directed graph, backlinks, autocomplete).
- SPEC-JOPLIN-004: Edit-to-Graph Real-Time Sync (onContentChange pipeline, 2s graph updates).

### Design Decisions
- DB connection method: HTTP API indirect access (not SQLite direct or CLI subprocess).
- Visualization library: D3.js (not vis.js or Cytoscape.js).
- Real-time sync: regex extraction on content change + full pipeline on save.

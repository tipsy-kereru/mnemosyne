# SPEC-JOPLIN-004: Edit-to-Graph Real-Time Sync

Generated: 2026-05-31 03:14:25 NZST
Status: completed
Priority: medium
Risk: medium
Source: Kuku-like real-time graph updates during editing
Depends on: SPEC-JOPLIN-002 (HTTP Bridge), SPEC-JOPLIN-003 (Visualization)

## 1. Problem Statement

Currently the Joplin plugin extracts entities only on explicit save (onNoteSave). Kuku updates its knowledge graph in real-time as the user types. For a responsive "second brain" experience, the graph should update as content changes, not only on save.

## 2. Goals

- Sync editor content changes to mnemosyne graph in near-real-time
- Update graph visualization within 2 seconds of content change
- Apply domain detection and scope metadata automatically
- Preserve existing note content — extraction is additive only

## 3. Non-Goals

- Running mnemosyne's full extraction pipeline (tree-sitter, SLM) on every keystroke
- Modifying the note content automatically (AI-assisted editing)
- Syncing changes back from graph to note

## 4. Facts

- Joplin plugin API has `onContentChange` event (not just `onNoteSave`)
- Current extraction uses regex patterns in `extractBasedOnDomain()`
- mnemosyne serve API (SPEC-JOPLIN-001) supports entity creation via POST
- Graph view (SPEC-JOPLIN-003) supports data updates with D3 transitions

## 5. Assumptions

- Regex extraction is sufficient for real-time preview (mnemosyne full pipeline runs on save)
- 500ms debounce is acceptable latency for graph updates
- Content change events fire on every keystroke in Joplin editor
- Only current note content is synced (not linked notes)

## 6. Requirements

### REQ-S4-001: Content Change Pipeline

On `onContentChange` event:
1. Debounce 500ms
2. Extract YAML frontmatter → session/scope metadata
3. Detect domain (daily/coding/legal) from content keywords
4. Run regex entity extraction (existing `extractBasedOnDomain()`)
5. POST extracted entities to mnemosyne serve via `MnemosyneClient`
6. Emit `graph-updated` event to graph view

### REQ-S4-002: Entity Diffing

Before sending to mnemosyne:
1. Compare extracted entities with previously extracted entities for this note
2. Only POST new/changed entities (skip unchanged)
3. Track extraction state per note ID
4. Clean up state when note is closed

### REQ-S4-003: Scope Auto-Application

When frontmatter contains scope metadata:
- `session_id` → set `scope_id` on all extracted entities
- `project` → set project context for mnemosyne query scoping
- `channel: joplin` → set `source_channel` on entities
- If no frontmatter, use project auto-detection from file path

### REQ-S4-004: Graph View Update

On `graph-updated` event:
1. Re-fetch affected entities from mnemosyne
2. Update D3 force simulation data
3. Animate node additions (fade in) and removals (fade out)
4. Preserve current zoom/pan state
5. Highlight newly added nodes for 2 seconds

### REQ-S4-005: Status Indicator

Add sync status indicator in Joplin toolbar area:
- Green dot: synced with mnemosyne
- Yellow dot: syncing in progress
- Red dot: mnemosyne unavailable
- Entity count badge: "42 entities"

### REQ-S4-006: Full Pipeline on Save

On `onNoteSave` (explicit save):
1. Write note content to temp file
2. Call `mnemosyne add tempfile --domain {domain} --scope-id {scope}` via child_process
3. This triggers full extraction pipeline (tree-sitter/SLM/LLM)
4. Compare full extraction results with regex preview
5. Update graph with richer entity data

## 7. Acceptance Criteria

| ID | Criterion | Verification |
|---|---|---|
| AC-S4-001 | Typing text updates graph within 2 seconds | Type entity-matching text, verify graph updates |
| AC-S4-002 | Save triggers full mnemosyne extraction | Save note, verify tree-sitter entities appear |
| AC-S4-003 | Frontmatter scope applied to entities | Add YAML frontmatter, verify scope_id set |
| AC-S4-004 | Graph animates node additions | Add new entity text, verify node fades in |
| AC-S4-005 | Status indicator reflects connection state | Stop mnemosyne serve, verify red dot |

## 8. Risks

| ID | Risk | Mitigation |
|---|---|---|
| RK-S4-001 | Debounce too aggressive, misses rapid edits | Tune to 500ms, add force-flush on save |
| RK-S4-002 | Regex extraction creates duplicate entities | Deduplicate by type+name+scope before POST |
| RK-S4-003 | Full pipeline on save too slow | Run async, show progress indicator |

## 9. Task Breakdown

| Task | Description | Dependencies |
|---|---|---|
| T1: Content Pipeline | Implement debounced onContentChange handler | SPEC-JOPLIN-002 |
| T2: Diffing | Entity diffing logic before API calls | T1 |
| T3: Scope | Frontmatter parsing + scope application | T1 |
| T4: Graph Update | graph-updated event → D3 data refresh | SPEC-JOPLIN-003 |
| T5: Status | Sync status indicator component | T1 |
| T6: Full Pipeline | onNoteSave → mnemosyne add child_process | SPEC-JOPLIN-001 |
| T7: Tests | Integration tests for sync pipeline | T1-T6 |

## 10. Files to Create/Modify

| File | Action |
|---|---|
| `joplin-plugin/knowledge-graph/src/sync_pipeline.ts` | NEW — content change pipeline |
| `joplin-plugin/knowledge-graph/src/entity_differ.ts` | NEW — entity diffing |
| `joplin-plugin/knowledge-graph/src/status_indicator.ts` | NEW — sync status UI |
| `joplin-plugin/knowledge-graph/src/index.ts` | MODIFY — add onContentChange handler |
| `joplin-plugin/knowledge-graph/src/graph_view.ts` | MODIFY — add graph-updated event handler |

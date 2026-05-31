# SPEC-JOPLIN-003: Real-Time Graph Visualization

Generated: 2026-05-31 03:14:25 NZST
Status: completed
Priority: high
Risk: medium
Source: Kuku-like graph visualization in Joplin plugin
Depends on: SPEC-JOPLIN-002 (HTTP Bridge)

## 1. Problem Statement

The current Joplin plugin graph view is a minimal HTML canvas stub that renders nothing meaningful. Kuku provides an interactive 2D/3D knowledge graph with force-directed layout, domain-colored nodes, clickable entities, and zoom/pan navigation. The plugin needs a proper graph visualization that shows entities, relations, backlinks, and allows navigation.

## 2. Goals

- Replace canvas stub with D3.js force-directed graph
- Show entities as nodes colored by domain (daily/coding/legal)
- Show relations as directed edges with labels
- Support click-to-inspect, double-click-to-navigate
- Add backlinks panel showing incoming connections
- Add wikilink autocomplete dropdown on `[[` input

## 3. Non-Goals

- 3D graph visualization (future consideration)
- Custom graph layout algorithms
- Graph editing (drag-to-rearrange only, no relation creation)
- Export graph as image

## 4. Facts

- Joplin panel webview supports full HTML/CSS/JS
- D3.js v7 runs in any browser context
- Current graph stub at `index.ts:showGraphView()` uses raw canvas
- mnemosyne entities have `type`, `name`, `properties`, `scope_id`
- Relations have `source`, `target`, `relationType`

## 5. Assumptions

- D3.js loaded from CDN or bundled with plugin
- Graph panel opens as Joplin side panel or separate window
- Max 500 nodes visible at once (performance constraint)
- Node click triggers entity detail view, not note navigation

## 6. Requirements

### REQ-S3-001: Force-Directed Graph

Implement D3.js force-directed graph in panel webview:
- Nodes represent entities, sized by relation count
- Edges represent relations, directed (arrows)
- Force simulation: charge, center, link forces
- Domain-based node coloring:
  - daily: green (#4CAF50)
  - coding: blue (#2196F3)
  - legal: orange (#FF9800)
- Zoom and pan via D3 zoom behavior
- Smooth transitions on data updates

### REQ-S3-002: Node Interaction

- Click node → show entity detail popup (type, name, properties, scope)
- Double-click node → navigate to related note in Joplin (if wikilink exists)
- Hover node → highlight connected edges and neighbor nodes
- Right-click node → context menu (search, backlinks, delete from graph)

### REQ-S3-003: Backlinks Panel

Add collapsible backlinks panel below editor:
- Show all relations where current note's entities are targets
- Format: `[source_type:source_name] → [relation_type] → [current_entity]`
- Click backlink → navigate to source entity or note
- Update on note change (debounced)

### REQ-S3-004: Wikilink Autocomplete

On `[[` input in editor:
- Query mnemosyne search API for matching entities
- Show dropdown: `entity_type:entity_name` with domain color dot
- Arrow keys to navigate, Enter to insert
- Debounce 300ms after last keystroke
- Show max 10 results

### REQ-S3-005: Graph Filtering

Add filter controls in graph panel:
- Domain filter checkboxes (daily/coding/legal)
- Scope filter dropdown (current project / all)
- Search box to highlight matching nodes
- Depth control (1-hop / 2-hop from selected)

### REQ-S3-006: Performance

- Lazy rendering: only draw visible nodes after zoom/pan
- Web Worker for force simulation if node count > 200
- Request animation frame for smooth 60fps
- Debounced updates on data changes (500ms)

## 7. Acceptance Criteria

| ID | Criterion | Verification |
|---|---|---|
| AC-S3-001 | Graph renders with 100+ nodes without lag | Load test fixture, verify FPS > 30 |
| AC-S3-002 | Click node shows entity detail | Click any node, verify popup |
| AC-S3-003 | Backlinks panel shows incoming relations | Open note with backlinked entities |
| AC-S3-004 | Autocomplete dropdown appears on `[[` | Type `[[`, verify dropdown |
| AC-S3-005 | Domain filter hides/shows nodes | Toggle filter, verify graph updates |

## 8. Risks

| ID | Risk | Mitigation |
|---|---|---|
| RK-S3-001 | D3.js bundle size too large for Joplin panel | Use D3 subpackages (d3-force, d3-selection only) |
| RK-S3-002 | Performance with 500+ nodes | Web Worker + lazy rendering |
| RK-S3-003 | Autocomplete conflicts with Joplin editor | Test with Joplin content_script injection |

## 9. Task Breakdown

| Task | Description | Dependencies |
|---|---|---|
| T1: D3 Setup | Integrate D3.js, create force-directed graph component | SPEC-JOPLIN-002 |
| T2: Node Interaction | Click/hover/double-click handlers | T1 |
| T3: Backlinks | Backlinks panel component | SPEC-JOPLIN-002 |
| T4: Autocomplete | Wikilink autocomplete dropdown | SPEC-JOPLIN-002 |
| T5: Filtering | Domain/scope/search filter controls | T1 |
| T6: Performance | Web Worker, lazy rendering, debouncing | T1 |
| T7: Tests | Component tests with mock data | T1-T6 |

## 10. Files to Create/Modify

| File | Action |
|---|---|
| `joplin-plugin/knowledge-graph/src/graph_view.ts` | NEW — D3 graph component |
| `joplin-plugin/knowledge-graph/src/backlinks_panel.ts` | NEW — backlinks component |
| `joplin-plugin/knowledge-graph/src/autocomplete.ts` | NEW — wikilink autocomplete |
| `joplin-plugin/knowledge-graph/src/graph_worker.ts` | NEW — Web Worker for force simulation |
| `joplin-plugin/knowledge-graph/src/index.ts` | MODIFY — replace canvas stub with graph_view |
| `joplin-plugin/knowledge-graph/package.json` | MODIFY — add d3-force, d3-selection, d3-zoom |

# Context Handoff

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-05-31 03:14:25 NZST

## Current Status

Plan 2026-06-01: Performance tuning and hybrid high-performance optimization SPEC completed. 27 completed SPECs, 0 planned, 1 candidate (SPEC-WIKI-008). 527 tests pass. Package v0.2.0.

| Category | Status | Evidence |
|---|---|---|
| Completed SPECs | 27 | Audit 2026-06-01 |
| Active planned SPECs | 0 | All SPECs completed or deferred |
| Remaining candidate SPECs | 1 | SPEC-WIKI-008 |
| Full tests | PASS | 527 passed |
| Static checks | PASS | ruff clean |
| Benchmark harness | READY | 921 pages baseline; B2 PASS, B1/B4/B5/B6 MISS |
| Harness tracking | auto-tracked | `.moon-cell/` tracked via `!.moon-cell/` gitignore exception |
| Package version | 0.2.0 | pyproject.toml |

## SPECs Completed Since Last Handoff (2026-05-04)

### SPEC-ARCH-ASYNC-001: Async I/O (completed 2026-05-05)

| Requirement | Result |
|---|---|
| T3 implementation | Added async methods to URLFetcher and LLMBridge (commit 746be8b) |
| T4 tests | Tests included in async implementation commit |
| z.ai provider | OpenAI-compatible LLM bridge added for GLM models |
| GLM fixes | JSON mode, preamble suppression, max_tokens corrections |

### SPEC-PROJECT-REGISTRY-001: Project-Scoped Knowledge Graph (completed 2026-05-07)

| Requirement | Result |
|---|---|
| REQ-PR-001 | `projects` table added to knowledge.db with hash-based PK |
| REQ-PR-002 | `detect_project()` walks CWD for .git/pyproject.toml/go.mod markers |
| REQ-PR-003 | Auto-registration on `mnemosyne add`/`update` |
| REQ-PR-004 | `mnemosyne project` subcommand: list/show/register/unregister/migrate |
| REQ-PR-005 | Migration back-fills from existing scope_id values |

### Untracked Features (no SPEC)

| Feature | Commit | Notes |
|---|---|---|
| `mnemosyne skill install` | c153d8a | Install mnemosyne skill to agent skills directory |
| `mnemosyne skill update` | 8ae7e9d | Update installed mnemosyne skill to latest version |
| `mnemosyne hook install` | 2411ecd | Auto-sync hooks for git, claude, codex, gemini, copilot |

## Benchmark Results Summary (2026-05-06, 921 pages)

| Benchmark | Measured | Threshold | Result |
|---|---|---|---|
| B1 URL fetch ×10 (PDF) | 1.06s | >30s | MISS |
| B2 LLM batch ×5 | 187.38s | >60s | PASS |
| B4 wiki status | 0.19s | >1s | MISS |
| B5 wiki lint | 0.19s | >2s | MISS |
| B6 wiki rebuild dry-run | 0.14s | >5s | MISS |

Decision: SPEC-WIKI-008 → DEFERRED (all vault benchmarks well below thresholds).

## Remaining Candidate List

| Remaining Item | Candidate SPEC | Priority | Risk | Notes |
|---|---|---|---|---|
| Large wiki/vault index performance | SPEC-WIKI-008 | low | medium | Benchmark-gated; all thresholds MISS |
| External Tool Integration API | SPEC-JOPLIN-001 | high | medium | HTTP API for Joplin plugin; foundation for 002/003/004 |
| Joplin Plugin HTTP Bridge | SPEC-JOPLIN-002 | high | medium | Replace in-memory Map with mnemosyne API client |
| Real-Time Graph Visualization | SPEC-JOPLIN-003 | high | medium | D3.js graph, backlinks, autocomplete |
| Edit-to-Graph Real-Time Sync | SPEC-JOPLIN-004 | medium | medium | onContentChange pipeline, 2s updates |

## Joplin Integration SPEC Package (2026-05-31)

4 SPECs created for Kuku-parity Joplin plugin experience. Dependency chain:

```
SPEC-JOPLIN-001 (mnemosyne serve HTTP API)
  └─→ SPEC-JOPLIN-002 (Joplin plugin HTTP bridge)
        ├─→ SPEC-JOPLIN-003 (D3.js graph visualization)
        └─→ SPEC-JOPLIN-004 (edit-to-graph real-time sync)
```

Key design decisions:
- DB connection: HTTP API indirect access (not SQLite direct or CLI subprocess)
- Visualization: D3.js (not vis.js or Cytoscape.js)
- Sync strategy: regex on content change + full pipeline on save

## Decisions Made

| ID | Decision | Rationale |
|---|---|---|
| DEC-001 | Preserve `.moon-cell/` as harness source of truth | Existing Moon Cell convention and user asked to expose ignored artifacts |
| DEC-002 | Use `git add -f .moon-cell` instead of editing `.gitignore` | Satisfies tracking request without weakening local-only ignore defaults |
| DEC-003 | `semantic-contradictions` is explicit and local/offline | Avoids accidental semantic review and remote privacy exposure |
| DEC-004 | Semantic candidates are review items only | Prevents false certainty and keeps deterministic conflicts separate |
| DEC-005 | Raw source excerpts require explicit opt-in | Minimizes sensitive raw text exposure |
| DEC-006 | Discovery never mutates graph facts or deletes wiki pages | Semantic review cannot become automatic resolution/prune mechanism |
| DEC-007 | SPEC-ARCH-ASYNC-001 T3/T4 promoted to completed | Benchmark B2 exceeded threshold; async methods implemented and merged |
| DEC-008 | SPEC-PROJECT-REGISTRY-001 recorded as completed | Implementation merged 2026-05-07; all acceptance criteria met |
| DEC-009 | skill/hook/z.ai features recorded as untracked | No SPEC exists; retroactive SPEC creation not justified |
| DEC-010 | Joplin-mnemosyne connection via HTTP API | Decouples plugin from DB schema; allows remote mnemosyne in future |
| DEC-011 | D3.js for graph visualization | Industry standard, lightweight subpackages, Joplin webview compatible |
| DEC-012 | Dual sync: regex preview + full pipeline on save | Real-time responsiveness without expensive extraction on every keystroke |

## Recommended Next Action

1. Monitor large-vault benchmarks after SPEC-PERF-001 optimizations and evaluate index writing speeds.
2. Consider SPEC-WIKI-008 only if index build thresholds are exceeded.

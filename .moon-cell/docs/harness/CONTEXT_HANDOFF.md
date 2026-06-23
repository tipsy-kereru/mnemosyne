# Context Handoff

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-06-20 22:50:19 NZST

## Current Status

Plan 2026-06-20: Two new SPECs drafted from OpenKB architecture audit gap —
long-document indexing and NL query/chat. Both converted to Laplace draft
issues (ISSUE-0001, ISSUE-0002) awaiting human approval. 27 completed SPECs,
2 planned, 1 candidate. Laplace `.harness/` initialized (mixed tracking policy).

| Category | Status | Evidence |
|---|---|---|
| Completed SPECs | 27 | Audit 2026-06-01 |
| Active planned SPECs | 2 | SPEC-LONGDOC-001, SPEC-NLQUERY-001 |
| Remaining candidate SPECs | 1 | SPEC-WIKI-008 |
| Full tests | PASS | 527 passed |
| Static checks | PASS | ruff clean |
| Benchmark harness | READY | 921 pages baseline; B2 PASS, B1/B4/B5/B6 MISS |
| Harness tracking | auto-tracked | `.moon-cell/` tracked via `!.moon-cell/` gitignore exception |
| Laplace harness | initialized | `.harness/` created 2026-06-20; ISSUE-0001, ISSUE-0002 draft |
| Package version | 0.2.0 | pyproject.toml |

## 2026-06-20 SPEC Package: Long-Doc + NL Query

Gap source: OpenKB architecture audit. OpenKB ships PageIndex long-doc
retrieval + NL query/chat; mnemosyne lacks both. mnemosyne path preserves
zero-external-dependency + zero-LLM-first principles.

Dependency chain:
```
SPEC-LONGDOC-001 (self-contained tree indexer + retriever)
  └─→ SPEC-NLQUERY-001 (NL router + answer synthesizer + HTTP/MCP exposure)
```

Key design decisions (DEC-013..016):
- DEC-013: Self-contained tree indexer over external `pageindex` dep.
- DEC-014: SLM-first (GLiNER2) + LLM-fallback (LLMBridge) for indexer + synthesis.
- DEC-015: HTTP + MCP dual exposure for NL query.
- DEC-016: No-delete supersession for document trees + chat sessions.

## SPECs Completed Since Last Handoff (2026-06-01)

### SPEC-PERF-001: Hybrid Performance Optimization (completed 2026-06-01)

| Requirement | Result |
|---|---|
| REQ-PERF-001 | SQLite WAL + synchronous=NORMAL PRAGMA tuning |
| REQ-PERF-002 | mnemosyne-core Rust extension (PyO3/Maturin) |
| REQ-PERF-003 | Fast-path/slow-path editor decoupling |
| REQ-PERF-004 | RAM disk lock optimization (MNEMOSYNE_LOCK_DIR) |

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
| DEC-013 | Self-contained tree indexer (no `pageindex` dep) | Preserves mnemosyne zero-external-dependency principle |
| DEC-014 | SLM-first + LLM-fallback for indexer + synthesis | Consistent with 3-layer extraction model; zero-cost default path |
| DEC-015 | HTTP + MCP dual exposure for NL query | Reuses `mnemosyne serve` for Joplin, MCP for agents |
| DEC-016 | No-delete supersession for trees + chat | Matches SPEC-MCP-001 contract; status flip, no DELETE |

## Recommended Next Action

1. `/laplace:approve ISSUE-0001` then `/laplace:run ISSUE-0001` → implement SPEC-LONGDOC-001.
2. After ISSUE-0001 review-passed: `/laplace:approve ISSUE-0002` → SPEC-NLQUERY-001.
3. Monitor large-vault benchmarks; promote SPEC-WIKI-008 only if thresholds exceeded.

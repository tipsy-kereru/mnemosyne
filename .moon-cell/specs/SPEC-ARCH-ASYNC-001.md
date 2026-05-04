---
id: SPEC-ARCH-ASYNC-001
version: "0.2.0"
status: planned
created: "2026-05-03 08:35:34 NZST"
updated: "2026-05-04 08:06:03 NZST"
author: Moon Cell Harness
priority: low
risk: medium-high
owner_role: Solution Architect
reviewer_role: API Reviewer / Test Architect
implementation_role: Implementer
source_of_truth: .moon-cell/specs/SPEC-ARCH-ASYNC-001.md
related_backlog: "FUTURE-001 backlog: async I/O deferred pending API design decision"
---

# SPEC-ARCH-ASYNC-001: Async I/O Feasibility and API Boundary Design

Generated: 2026-05-03 08:35:34 NZST
Updated: 2026-05-04 08:06:03 NZST

Canonical location: `.moon-cell/specs/SPEC-ARCH-ASYNC-001.md`.

## Status

| Field | Value |
|---|---|
| Stage | Planned (promoted from candidate 2026-05-04) |
| T1 (I/O map + boundary proposal) | Complete — 2026-05-04 |
| T2 (API Reviewer) | Complete — 2026-05-04 |
| T3 (Implementation) | Not started — gated on benchmark evidence |
| T4 (Tests) | Not started — follows T3 |
| Promotion reason | User selected; T1/T2 design analysis executed in-session |

## Problem Statement

Prior production hardening identified many graph and pipeline I/O operations that could become
bottlenecks in concurrent or long-running usage. Blindly converting sync APIs to async would risk
breaking public contracts and tests. This SPEC decides whether async is needed, where boundaries
belong, and how compatibility is preserved.

## Goals

| ID | Goal |
|---|---|
| G-001-001 | Map current synchronous I/O hotspots and public API boundaries. |
| G-001-002 | Define whether async wrappers, native async APIs, worker pools, or no change is the right path. |
| G-001-003 | Preserve existing CLI and library behavior unless explicitly versioned. |
| G-001-004 | Create measurable acceptance criteria before implementation. |

## Non-Goals

| ID | Non-Goal |
|---|---|
| NG-001-001 | Do not rewrite the graph or ingest stack to async in this planning SPEC. |
| NG-001-002 | Do not introduce a new database or message queue. |
| NG-001-003 | Do not break existing synchronous callers. |

## Requirements

### REQ-ARCH-ASYNC-001: I/O map

**EARS:** When planning async work, the system shall inventory graph, raw-source, wiki, and extraction I/O hotspots with file references.

**Status: FULFILLED — see I/O Hotspot Map below.**

### REQ-ARCH-ASYNC-002: Boundary proposal

**EARS:** The SPEC shall choose sync-only, async wrappers, native async APIs, or hybrid boundaries with tradeoffs.

**Status: FULFILLED — see Boundary Decision below.**

### REQ-ARCH-ASYNC-003: Compatibility plan

**EARS:** Any future implementation shall preserve current sync APIs or provide a versioned migration path.

**Status: FULFILLED — see Compatibility Plan below.**

### REQ-ARCH-ASYNC-004: Benchmark criteria

**EARS:** Async work shall not proceed without measurable workloads and thresholds.

**Status: FULFILLED — see Benchmark Criteria below.**

## I/O Hotspot Map

Confirmed: zero `async def`, `await`, or `asyncio` usage across the entire codebase (2026-05-04).

### Zone 1: SQLite (synchronous, blocking)

| File | Location | Operation | Latency Profile |
|---|---|---|---|
| `mnemosyne/graph/knowledge_graph.py:77` | `KnowledgeGraph.__init__` | `sqlite3.connect()` | Local disk, <1ms typical |
| `mnemosyne/graph/knowledge_graph.py:260,319` | `add_entity`, `add_relation` | `conn.execute()` + `conn.commit()` | Local disk, <1ms |
| `mnemosyne/extraction/pipeline.py:36` | `IncrementalTracker.__init__` | Shared SQLite connection | Same connection as KnowledgeGraph |
| `mnemosyne/ingest/ingester.py:463` | `_ensure_cache_table` | Hash cache table in SQLite | Local disk, <1ms |

**Assessment**: SQLite is local, embedded, and fast. `check_same_thread=False` is already set. An `aiosqlite` wrapper would add thread overhead with no user-visible benefit for single-process CLI usage. **No async needed here.**

### Zone 2: Filesystem (synchronous, bulk)

| File | Location | Operation | Latency Profile |
|---|---|---|---|
| `mnemosyne/wiki/llm_wiki.py:420-422` | `status()` | `wiki_root.rglob("*.md")` — all pages | O(N) pages, typically <100ms |
| `mnemosyne/wiki/llm_wiki.py:467,473` | `lint()` | rglob + `read_text()` per page | O(N) reads, sequential |
| `mnemosyne/wiki/llm_wiki.py:869` | `_write_index()` | glob + write index page | O(N) glob |
| `mnemosyne/extraction/pipeline.py:405,473` | `_discover_files`, `_extract_file` | `rglob("*")` + `read_text()` per file | O(N) reads, sequential |
| `mnemosyne/wiki/llm_wiki.py:126-137` | `WikiWriteLock` | `os.open()` + `os.fdopen()` write | Single file, <1ms |

**Assessment**: Filesystem I/O is sequential and local. For typical wiki sizes (<1000 pages) this is fast. `aiofiles` would complicate the code with no meaningful gain unless vault size exceeds benchmarks. **No async needed unless benchmark evidence shows >2s lint/status on large vaults — see Benchmark Criteria.**

### Zone 3: Network + LLM API (synchronous, slow — primary candidate)

| File | Location | Operation | Latency Profile |
|---|---|---|---|
| `mnemosyne/ingest/url_fetcher.py:65` | `URLFetcher._open` | `urllib.request.urlopen(timeout=30)` | 1–30s per URL |
| `mnemosyne/ingest/llm_bridge.py:133-160` | `_call_anthropic`, `_call_openai` | Blocking LLM API call | 5–60s per call |
| `mnemosyne/ingest/llm_extractor.py:64` | `LLMExtractor.extract_text` | Calls `LLMBridge.extract()` per chunk | N × LLM latency |

**Assessment**: These are the only operations with user-visible latency. For batch ingest of N URLs or N files with LLM extraction, the total time is `N × per-call latency` (serial). This is the only zone where async/concurrency provides a real benefit. **Primary candidate for async implementation — gated on benchmark evidence.**

## Boundary Decision

### Decision: Targeted async for Network + LLM zone only (Option B)

Three options were evaluated:

| Option | Description | Decision |
|---|---|---|
| A: No change | Keep all sync; document known serial bottleneck | Rejected — leaves multi-URL ingest unnecessarily slow |
| **B: Targeted async (LLMBridge + URLFetcher)** | `asyncio.gather()` for parallel calls; sync CLI wrappers via `asyncio.run()` | **Selected** |
| C: Full async pipeline | Convert `ExtractionPipeline.run()`, `Ingester.add_directory()`, SQLite to async | Rejected — high complexity, API churn, no proportional benefit for local I/O |

**Selected boundary (B):**
- `mnemosyne/ingest/url_fetcher.py`: add `async def fetch_async()` alongside existing `fetch()` (no rename)
- `mnemosyne/ingest/llm_bridge.py`: add `async def extract_async()` alongside existing `extract()` (no rename)
- `mnemosyne/ingest/ingester.py`: add `add_urls_async(urls: list[str])` for batch URL ingest; existing `add()` stays sync
- All async methods are **additive only** — zero changes to existing sync public API
- CLI entry points remain sync; batch paths use `asyncio.run()` internally

### Compatibility Contract

| Component | Change | Compatibility |
|---|---|---|
| `URLFetcher.fetch()` | No change | Preserved exactly |
| `URLFetcher.fetch_async()` | New additive method | No existing callers |
| `LLMBridge.extract()` | No change | Preserved exactly |
| `LLMBridge.extract_async()` | New additive method | No existing callers |
| `Ingester.add()` | No change | Preserved exactly |
| `Ingester.add_urls_async()` | New additive method | No existing callers |
| CLI commands | No change | Preserved exactly |
| `KnowledgeGraph` | No change | Preserved exactly |
| `LLMWiki` | No change | Preserved exactly |

## Compatibility Plan

1. All async methods are new additions; no existing method is renamed or removed.
2. Existing tests continue to run without modification.
3. New async methods require new focused tests in `tests/test_url_fetcher_async.py` and `tests/test_llm_bridge_async.py`.
4. `asyncio.run()` wrappers are used at CLI boundaries so async internals do not leak to callers.
5. If a future refactor wants to remove sync variants, that requires a separate versioned SPEC.

## Benchmark Criteria

Implementation (T3/T4) shall not proceed until the following benchmarks are run and thresholds are exceeded:

| Benchmark | Command | Threshold to Proceed |
|---|---|---|
| Serial URL ingest (10 URLs) | `time python -m mnemosyne.ingest.cli add <10 urls>` | >30s total → async justified |
| Parallel URL ingest baseline | Manual: 10 `urllib.urlopen()` calls timed | >5× faster with `asyncio.gather` |
| LLM batch ingest (5 files) | `time mnemosyne add <5 files>` with LLM provider set | >60s total → async justified |
| Wiki lint on large vault | `time mnemosyne wiki lint` on 500+ page vault | >2s → filesystem async considered |

If no threshold is exceeded, T3 is deferred indefinitely. The design document (T1/T2) is the deliverable of this SPEC for now.

## Risks

| Risk ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-ARCH-ASYNC-001 | API churn | High | Additive-only async methods; no renames. |
| R-ARCH-ASYNC-002 | False performance win | Medium | Benchmark gate before T3 starts. |
| R-ARCH-ASYNC-003 | Concurrency corruption in SQLite | High | SQLite zone excluded from async; `check_same_thread=False` already set for existing patterns. |
| R-ARCH-ASYNC-004 | Test suite divergence | Medium | Async methods tested separately; existing sync tests unchanged. |

## Open Questions

| ID | Question | Owner |
|---|---|---|
| OQ-001 | Should `add_urls_async()` be on `Ingester` or a new `BatchIngester` class? | Resolved at T3 start — prefer same class for API simplicity |
| OQ-002 | httpx vs asyncio+urllib for URL fetching? | Prefer httpx (cleaner async API, no new vendored dependency at sync layer) |
| OQ-003 | Should LLM async use semaphore to limit concurrent calls? | Yes — default concurrency limit of 5 to avoid rate limiting |

## Suggested Task Breakdown

| Task ID | Owner Role | Description | Verification |
|---|---|---|---|
| SPEC-ARCH-ASYNC-001-T1 | Solution Architect | I/O map + boundary decision + compatibility plan | **Complete 2026-05-04** |
| SPEC-ARCH-ASYNC-001-T2 | API Reviewer / Test Architect | Risk, compatibility, and benchmark criteria review | **Complete 2026-05-04** |
| SPEC-ARCH-ASYNC-001-T3 | Implementer | Implement async methods (gated on benchmark evidence) | ruff + mypy + focused tests pass |
| SPEC-ARCH-ASYNC-001-T4 | Test Architect | `tests/test_url_fetcher_async.py`, `tests/test_llm_bridge_async.py`, full suite pass | 465+ tests pass; no regressions |

## Verification Commands

For T1/T2 (planning phase — complete):
- Read-only architecture analysis: no product code changes
- All requirements fulfilled in this document

For T3/T4 (implementation phase — gated):
- `python -m pytest tests/test_url_fetcher_async.py tests/test_llm_bridge_async.py -v`
- `python -m pytest --tb=short` (full suite, no regressions)
- `ruff check mnemosyne tests`
- `mypy mnemosyne`
- `git diff --check`

## Definition of Done

| ID | Check | Required Result |
|---|---|---|
| DOD-SPEC-ARCH-ASYNC-001-001 | T1/T2 design | I/O map, boundary decision, compatibility plan, benchmark criteria documented | ✅ Complete |
| DOD-SPEC-ARCH-ASYNC-001-002 | Benchmark gate | At least one threshold exceeded before T3 starts | ❌ Not met — 10 URLs: 1.28s total (threshold: >30s); wiki: 0 pages (threshold: 500+) |
| DOD-SPEC-ARCH-ASYNC-001-003 | T3 implementation | Additive async methods only; no sync API changes | Pending T3 |
| DOD-SPEC-ARCH-ASYNC-001-004 | T4 tests | Focused async tests + full suite pass + static checks | Pending T4 |
| DOD-SPEC-ARCH-ASYNC-001-005 | Docs/harness | Manifest, task routing, changelog, and handoff updated | Pending T3/T4 |

## Notes

T1 and T2 are the primary deliverables of this SPEC for now. The design is complete.
T3/T4 (implementation) require benchmark evidence before starting.
No product code was changed during the T1/T2 planning pass.

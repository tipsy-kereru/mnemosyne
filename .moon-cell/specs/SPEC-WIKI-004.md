---
id: SPEC-WIKI-004
version: "0.1.0"
status: completed
created: "2026-05-02 13:19:03 NZST"
updated: "2026-05-03 07:59:27 NZST"
author: Moon Cell Harness
priority: high
risk: medium
owner_role: Spec Architect / Solution Architect
reviewer_role: Test Architect / Reliability Reviewer
implementation_role: Implementer
source_of_truth: .moon-cell/specs/SPEC-WIKI-004.md
related_backlog: "FUTURE-006"
---

# SPEC-WIKI-004: Multi-Process Concurrent Wiki Writer Locking

Generated: 2026-05-02 13:19:03 NZST
Updated: 2026-05-03 07:59:27 NZST

Canonical location: `.moon-cell/specs/SPEC-WIKI-004.md`.

## Status

| Field | Value |
|---|---|
| Stage | Completed |
| Parent work | SPEC-WIKI-001 added atomic writes but not inter-process locking |
| Target gate | QG-006 plus concurrency stress/regression tests |
| Implementation completed | 2026-05-03 07:59:27 NZST |

## Problem Statement

SPEC-WIKI-001 writes wiki pages atomically with temp-file plus replace, which reduces partial-file risk. Atomic writes do not fully prevent lost updates when two `mnemosyne add/update/wiki rebuild` processes edit the same wiki root around the same time. Manual notes could also be preserved from a stale read and overwrite a newer manual note or generated section.

The wiki writer needs a dependency-free, cross-platform-enough single-writer guard for wiki maintenance operations.

## Goals

| ID | Goal |
|---|---|
| G-WIKI-004-001 | Prevent concurrent Mnemosyne processes from writing the same wiki root simultaneously by default. |
| G-WIKI-004-002 | Provide clear timeout, stale-lock, and error behavior. |
| G-WIKI-004-003 | Keep locks local to the wiki root and safe for temp/test roots. |
| G-WIKI-004-004 | Preserve atomic writes as the final write discipline after lock acquisition. |

## Non-Goals

| ID | Non-Goal |
|---|---|
| NG-WIKI-004-001 | Do not implement distributed/network filesystem locking guarantees. |
| NG-WIKI-004-002 | Do not depend on a new third-party lock package unless a separate dependency decision approves it. |
| NG-WIKI-004-003 | Do not lock ordinary read-only `wiki status` unless evidence shows it is required. |
| NG-WIKI-004-004 | Do not silently break existing single-process CLI usage. |

## Current Evidence

| Evidence | Result | Source |
|---|---|---|
| Atomic writes exist | Generated pages use temp file plus `os.replace()` | `mnemosyne/wiki/llm_wiki.py` |
| Multiple write entry points exist | ingest add/update and wiki rebuild can write wiki files | `mnemosyne/ingest/ingester.py`, `mnemosyne/wiki/cli.py` |
| Manual notes are preserved from existing file reads | Stale read/write interleavings could lose manual note changes | SPEC-WIKI-001 implementation behavior |

## Locking Policy

| Policy ID | Policy | Decision |
|---|---|---|
| LOCK-POL-001 | Lock scope | One lock file per wiki root, e.g. `<wiki-root>/.mnemosyne-wiki.lock` |
| LOCK-POL-002 | Write commands | `add`, `update`, and `wiki rebuild` acquire the wiki-root write lock before reading/writing generated pages |
| LOCK-POL-003 | Read commands | `wiki status` and `wiki lint` remain read-only and do not lock by default |
| LOCK-POL-004 | Timeout | Default timeout should be short and configurable, e.g. 10 seconds |
| LOCK-POL-005 | Stale lock | Lock metadata records PID, hostname, created_at; stale handling is explicit and conservative |
| LOCK-POL-006 | Dependencies | Use stdlib-only locking strategy first |

## Requirements

### REQ-WIKI-004-001: Wiki Root Write Lock

**EARS:** When a command writes generated wiki pages, the system shall acquire a wiki-root write lock before reading or writing those pages.

Acceptance criteria:
- `LLMWikiMaintainer` or a helper provides a context manager for write operations.
- `mnemosyne add`, `mnemosyne update`, and `mnemosyne wiki rebuild` use the lock when wiki writing is enabled.
- Lock files live inside the wiki root and are ignored by generated index listings.

### REQ-WIKI-004-002: Timeout and Error Behavior

**EARS:** When a write lock cannot be acquired, the command shall fail clearly instead of proceeding unsafely.

Acceptance criteria:
- Default timeout is documented.
- CLI error includes lock path and safe retry guidance.
- JSON output exposes a stable lock-error code when applicable.

### REQ-WIKI-004-003: Stale Lock Metadata

**EARS:** When a lock is created, it shall record diagnostic metadata for stale-lock analysis.

Acceptance criteria:
- Metadata includes PID, hostname, process start timestamp or lock creation timestamp, command/action when available.
- Stale lock detection is conservative and tested.
- Forced lock break is not automatic unless an explicit flag is added.

### REQ-WIKI-004-004: Cross-Platform Stdlib Implementation

**EARS:** When locking is implemented, it shall avoid new dependencies and work on Linux/macOS at minimum.

Acceptance criteria:
- Prefer atomic lock-file creation with `os.open(..., O_CREAT | O_EXCL)` or an equivalent stdlib strategy.
- Cleanup removes only the lock owned by the current process/context.
- Tests avoid relying on platform-specific timing flakiness.

### REQ-WIKI-004-005: Concurrency Regression Tests

**EARS:** When two wiki writers run concurrently, one shall wait/fail according to timeout policy and generated pages shall remain valid.

Acceptance criteria:
- Unit tests simulate held lock and timeout.
- Integration-style test verifies second writer does not corrupt generated page content.
- `git diff --check`, focused tests, and full tests pass.

## Risks

| Risk ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-WIKI-004-001 | Lock file left behind after crash | Future writes blocked | Metadata and explicit stale-lock guidance |
| R-WIKI-004-002 | Network filesystem semantics differ | Lock may be unreliable on shared drives | Document local-filesystem support only |
| R-WIKI-004-003 | Over-locking read-only commands | Slower status/lint UX | Lock only write commands initially |
| R-WIKI-004-004 | Flaky concurrency tests | CI instability | Use deterministic held-lock tests before true process races |

## Suggested Task Breakdown

| Task ID | Owner Role | Description | Verification |
|---|---|---|---|
| WIKI-004-T1 | Solution Architect | Finalize lock helper API and timeout defaults | Design review against CLI entry points |
| WIKI-004-T2 | Implementer | Add stdlib write-lock context manager | Unit tests for acquire/release/timeout |
| WIKI-004-T3 | Implementer | Wire lock into ingest add/update and wiki rebuild | CLI tests pass |
| WIKI-004-T4 | Test Architect | Add held-lock and non-corruption regression tests | Focused tests pass reliably |
| WIKI-004-T5 | Writer | Document stale-lock recovery guidance | README/manual updated |

## Verification Commands

```bash
python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py --tb=short -q
pytest -q
ruff check mnemosyne tests
mypy mnemosyne
git diff --check
```

## Definition of Done

| ID | Check | Required Result |
|---|---|---|
| DOD-WIKI-004-001 | Locking | Write commands acquire a wiki-root lock before page refresh |
| DOD-WIKI-004-002 | Timeout | Contended lock fails clearly with stable error details |
| DOD-WIKI-004-003 | Safety | Lock cleanup cannot remove another process's lock |
| DOD-WIKI-004-004 | Tests | Held-lock and non-corruption tests pass without flakes |
| DOD-WIKI-004-005 | Docs | Timeout/stale-lock guidance documented |
| DOD-WIKI-004-006 | Quality | Focused tests, full tests, ruff, mypy, diff hygiene pass |


## Implementation Result

Completed: 2026-05-03 07:59:27 NZST

| Requirement | Result | Evidence |
|---|---|---|
| REQ-WIKI-004-001 | PASS | `LLMWikiMaintainer.write_lock()` and `WikiWriteLock` provide a wiki-root write lock; `update_from_ingest()` and write-mode `rebuild_from_graph()` acquire it |
| REQ-WIKI-004-002 | PASS | `WikiLockError` includes lock path, timeout, retry guidance, holder metadata, and stable JSON code `wiki-lock-timeout` |
| REQ-WIKI-004-003 | PASS | Lock metadata includes owner token, PID, hostname, created_at, action, and wiki_root; stale detection is diagnostic and non-destructive |
| REQ-WIKI-004-004 | PASS | Lock acquisition uses stdlib atomic `os.open(..., O_CREAT | O_EXCL)` and release removes only the current owner token |
| REQ-WIKI-004-005 | PASS | Tests cover held-lock timeout, stale-lock diagnostics, foreign-lock cleanup safety, and rebuild non-corruption under contention |

Verification evidence:

```text
python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py --tb=short -q
39 passed in 0.58s

pytest -q
456 passed in 11.20s

ruff check mnemosyne tests
All checks passed!

mypy mnemosyne
Success: no issues found in 37 source files

python -m mnemosyne wiki rebuild/status/lint --format json --lock-timeout 1
CLI smoke passed against temp DB/wiki roots
```

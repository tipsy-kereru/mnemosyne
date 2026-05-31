---
id: SPEC-WARN-001
version: "0.1.0"
status: completed
created: "2026-04-29"
updated: "2026-04-30 15:43:25 NZST"
author: Moon Cell Harness
priority: medium
risk: medium
owner_role: Spec Architect
reviewer_role: Test Architect
implementation_role: Implementer
source_of_truth: .moon-cell/specs/SPEC-WARN-001.md
related_backlog: "FUTURE-002"
---

# SPEC-WARN-001: Systematic Pytest Warning Remediation

Generated: 2026-04-29 17:48:39 NZST
Updated: 2026-04-30 15:43:25 NZST

Canonical location: `.moon-cell/specs/SPEC-WARN-001.md`.

## Status

| Field | Value |
|---|---|
| Stage | Completed |
| Harness style | Moon Cell controlled, SPEC-first lite, Karpathy guarded |
| Approval gate | G-SPEC satisfied by user request on 2026-04-29 |
| Implementation gate | Completed by `$moon-cell:run SPEC-WARN-001` on 2026-04-30 |
| Target quality gate | QG-005: Warning Cleanliness |

## Problem Statement

The baseline test suite passed, but pytest emitted 417 warnings. The warning summary shows all reported warnings originate from project-owned uses of deprecated `datetime.datetime.utcnow()`. These warnings create noise, reduce future Python compatibility, and weaken the usefulness of warning output as a signal.

## Evidence

Command run on 2026-04-29:

```bash
python3 -m pytest --tb=short -q
```

Observed result:

```text
413 passed, 2 skipped, 417 warnings
```

Warning sources from pytest summary:

| Source File | Line | Warning Type | Approx. Warning Count | Triggered By Tests |
|---|---:|---|---:|---|
| `mnemosyne/graph/scope_manager.py` | 98 | `DeprecationWarning: datetime.utcnow()` | 142 | `tests/test_knowledge_graph_session.py`, `tests/test_scope_manager.py` |
| `mnemosyne/graph/knowledge_graph.py` | 244 | `DeprecationWarning: datetime.utcnow()` | 127 | `tests/test_knowledge_graph_session.py`, `tests/test_pipeline.py`, `tests/test_pipeline_integration.py`, `tests/test_scope_manager.py` |
| `mnemosyne/graph/knowledge_graph.py` | 303 | `DeprecationWarning: datetime.utcnow()` | 16 | `tests/test_knowledge_graph_session.py`, `tests/test_pipeline.py`, `tests/test_pipeline_integration.py` |
| `mnemosyne/extraction/pipeline.py` | 82 | `DeprecationWarning: datetime.utcnow()` | 39 | `tests/test_pipeline.py`, `tests/test_pipeline_integration.py` |
| `mnemosyne/extraction/pipeline.py` | 281 | `DeprecationWarning: datetime.utcnow()` | 31 | `tests/test_pipeline.py`, `tests/test_pipeline_integration.py` |
| `mnemosyne/extraction/pipeline.py` | 639 | `DeprecationWarning: datetime.utcnow()` | 31 | `tests/test_pipeline.py`, `tests/test_pipeline_integration.py` |
| `mnemosyne/extraction/pipeline.py` | 375 | `DeprecationWarning: datetime.utcnow()` | 31 | `tests/test_pipeline.py`, `tests/test_pipeline_integration.py` |

Static grep evidence:

```text
mnemosyne/graph/scope_manager.py:98: datetime.utcnow().isoformat()
mnemosyne/graph/knowledge_graph.py:244: datetime.utcnow().isoformat()
mnemosyne/graph/knowledge_graph.py:303: datetime.utcnow().isoformat()
mnemosyne/extraction/pipeline.py:82: datetime.utcnow().isoformat()
mnemosyne/extraction/pipeline.py:281: datetime.utcnow().isoformat()
mnemosyne/extraction/pipeline.py:375: datetime.utcnow().isoformat()
mnemosyne/extraction/pipeline.py:639: datetime.utcnow().isoformat()
```

## Goals

| ID | Goal |
|---|---|
| G-001 | Eliminate project-owned pytest warnings from deprecated UTC timestamp creation. |
| G-002 | Preserve existing graph, scope, pipeline, and report behavior unless intentionally changed and tested. |
| G-003 | Establish a repeatable warning-cleanliness gate so future warnings are caught early. |
| G-004 | Keep the implementation small, dependency-free, and reversible. |

## Non-Goals

| ID | Non-Goal |
|---|---|
| NG-001 | Do not redesign graph storage, scope hierarchy, or extraction pipeline behavior. |
| NG-002 | Do not introduce async I/O. That remains FUTURE-001. |
| NG-003 | Do not add new runtime dependencies. |
| NG-004 | Do not change historical rows already stored in existing SQLite databases. |
| NG-005 | Do not suppress warnings globally as a substitute for fixing project-owned warning sources. |

## Key Decision Required

### DEC-WARN-001: Timestamp Format Policy

Current code stores timestamps as naive UTC ISO strings, for example:

```text
2026-04-29T05:48:39.123456
```

Replacing `datetime.utcnow()` with `datetime.now(timezone.utc).isoformat()` produces offset-aware strings, for example:

```text
2026-04-29T05:48:39.123456+00:00
```

The implementation must choose one of these policies before editing source:

| Option | Description | Pros | Cons | Recommendation |
|---|---|---|---|---|
| A | Preserve naive UTC string shape using `datetime.now(timezone.utc).replace(tzinfo=None).isoformat()` | Minimal behavior/output change; safest for existing tests and stored data conventions | Internally discards timezone after using timezone-aware clock | Recommended for this warning cleanup SPEC |
| B | Migrate new timestamps to offset-aware UTC strings using `datetime.now(timezone.utc).isoformat()` | Semantically clearer and matches Python warning guidance | Public/output/storage string shape changes; may require broader tests and migration notes | Defer to a separate timestamp semantics SPEC if desired |

Decision: Use Option A for SPEC-WARN-001 unless the user explicitly chooses a broader timestamp semantics migration.

## Requirements

### REQ-001: Centralize UTC Timestamp Creation

**EARS:** When project code needs a current UTC ISO timestamp for graph, scope, or pipeline metadata, the system shall call one project-owned helper instead of calling `datetime.utcnow()` directly.

Acceptance criteria:

- A small helper exists in an appropriate existing module or minimal new utility module.
- The helper uses `datetime.now(timezone.utc)` internally.
- The helper returns a string compatible with the selected timestamp format policy.
- No new third-party dependency is introduced.

### REQ-002: Replace Deprecated Calls

**EARS:** The system shall replace all project-owned `datetime.utcnow()` calls in `mnemosyne/graph/scope_manager.py`, `mnemosyne/graph/knowledge_graph.py`, and `mnemosyne/extraction/pipeline.py`.

Acceptance criteria:

- Static search finds no `datetime.utcnow` usage in `mnemosyne/`.
- All replaced call sites still produce ISO-8601-compatible strings.
- The graph/session/pipeline tests continue to pass.

### REQ-003: Preserve Current Behavior

**EARS:** The system shall preserve existing behavior for scope creation, graph entity/relation writes, incremental pipeline cache metadata, and extraction reports.

Acceptance criteria:

- Existing tests pass without requiring broad assertion rewrites.
- If timestamp assertion tests are added or updated, they validate shape and parseability without depending on exact wall-clock values.
- Existing data reading remains backward compatible with prior naive UTC strings.

### REQ-004: Add Warning Regression Coverage

**EARS:** The system shall add a warning-cleanliness regression check that fails if project-owned `DeprecationWarning` instances reappear during the relevant test subset.

Acceptance criteria:

- At least one targeted test or command validates the affected modules under `DeprecationWarning` as errors.
- The verification command is documented in `QUALITY_GATES.md` as QG-005.
- The full test suite reports zero warnings or, if third-party warnings appear later, zero project-owned warnings from `mnemosyne/`.

### REQ-005: Refresh Harness Evidence After Implementation

**EARS:** After implementation, the harness shall record the new warning count, commands run, files changed, and any remaining warning sources.

Acceptance criteria:

- `.moon-cell/docs/harness/CHANGELOG.md` gets an implementation entry.
- `.moon-cell/docs/harness/CONTEXT_HANDOFF.md` records verification evidence.
- `.moon-cell/docs/harness/TASK_ROUTING.md` marks SPEC-WARN-001 completed only after verification passes.

## Cleanup Plan

This SPEC is cleanup/refactor-shaped, so behavior must be protected before edits.

1. Baseline current warning output with `python3 -m pytest --tb=short -q`.
2. Add or identify tests that exercise the affected timestamp call paths.
3. Introduce the minimal timestamp helper.
4. Replace each deprecated call site one file at a time.
5. Run targeted warning-as-error checks for affected tests.
6. Run full quality gate and inspect warning output.
7. Update harness evidence and mark SPEC status only after verification.

## Files to Modify During Implementation

| File | Requirement | Change Type |
|---|---|---|
| `mnemosyne/graph/scope_manager.py` | REQ-001, REQ-002 | Replace deprecated timestamp call |
| `mnemosyne/graph/knowledge_graph.py` | REQ-001, REQ-002 | Replace deprecated timestamp calls |
| `mnemosyne/extraction/pipeline.py` | REQ-001, REQ-002 | Replace deprecated timestamp calls |
| `mnemosyne/<timestamp helper location>.py` or existing utility module | REQ-001 | Add minimal helper if no existing utility fits |
| `tests/**` | REQ-003, REQ-004 | Add or update targeted regression tests if needed |
| `.moon-cell/docs/harness/QUALITY_GATES.md` | REQ-004 | Add QG-005 warning-cleanliness gate |
| `.moon-cell/docs/harness/CHANGELOG.md` | REQ-005 | Record implementation result |
| `.moon-cell/docs/harness/CONTEXT_HANDOFF.md` | REQ-005 | Record implementation evidence |
| `.moon-cell/docs/harness/TASK_ROUTING.md` | REQ-005 | Update status |

## Suggested Task Breakdown

| Task ID | Owner Role | Description | Verification |
|---|---|---|---|
| WARN-T1 | Test Architect | Identify or add targeted coverage for timestamp-producing graph/scope/pipeline paths | Targeted tests fail or warn before source fix when warnings are errors |
| WARN-T2 | Implementer | Add minimal timestamp helper using `datetime.now(UTC)` | Unit test or direct parser check validates ISO output |
| WARN-T3 | Implementer | Replace deprecated calls in graph and scope modules | Scope/knowledge graph tests pass with deprecations as errors |
| WARN-T4 | Implementer | Replace deprecated calls in pipeline module | Pipeline tests pass with deprecations as errors |
| WARN-T5 | Reviewer | Run full suite and warning gate, inspect diff for timestamp behavior drift | Full tests pass; warning count reduced to target |
| WARN-T6 | Handoff Writer | Update harness artifacts and SPEC status | Changelog/handoff/task routing current |

## Verification Commands

Minimum implementation verification:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -W error::DeprecationWarning -m pytest tests/test_scope_manager.py tests/test_knowledge_graph_session.py tests/test_pipeline.py tests/test_pipeline_integration.py --tb=short -q
python3 -m pytest --tb=short -q
python3 -m ruff check mnemosyne/ tests/
mypy --ignore-missing-imports mnemosyne/
```

Recommended static verification:

```bash
grep -R "datetime.utcnow" -n mnemosyne tests --exclude-dir=__pycache__
```

Expected static result after implementation:

```text
(no matches in mnemosyne/)
```

## Definition of Done

| ID | Check | Required Result |
|---|---|---|
| DOD-001 | Full tests | Pass |
| DOD-002 | Warning count | Zero project-owned warnings; target zero total pytest warnings |
| DOD-003 | Static search | No `datetime.utcnow` in `mnemosyne/` |
| DOD-004 | Lint/type | ruff and mypy pass |
| DOD-005 | Behavior | Existing graph/scope/pipeline behavior preserved |
| DOD-006 | Harness | CHANGELOG, CONTEXT_HANDOFF, TASK_ROUTING updated |

## Implementation Result

Completed: 2026-04-30 15:43:25 NZST

| Requirement | Result | Evidence |
|---|---|---|
| REQ-001 | PASS | Added `mnemosyne/timestamps.py::utc_now_iso()` using `datetime.now(timezone.utc).replace(tzinfo=None).isoformat()` |
| REQ-002 | PASS | Replaced project timestamp call sites in `scope_manager.py`, `knowledge_graph.py`, and `pipeline.py`; static grep has no `datetime.utcnow` matches outside ignored caches |
| REQ-003 | PASS | Helper preserves naive UTC ISO string shape; added `tests/test_timestamps.py` |
| REQ-004 | PASS | QG-005 affected subset passes with `DeprecationWarning` as errors and plugin autoload disabled to avoid unrelated pytest plugin warnings |
| REQ-005 | PASS | Harness changelog, handoff, task routing, and manifest updated |

Verification evidence:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -W error::DeprecationWarning -m pytest tests/test_scope_manager.py tests/test_knowledge_graph_session.py tests/test_pipeline.py tests/test_pipeline_integration.py --tb=short -q
128 passed in 11.06s

grep -R "datetime.utcnow" -n mnemosyne tests --exclude-dir=__pycache__
(no output)

python3 -m pytest --tb=short -q
441 passed in 12.78s

python3 -m ruff check mnemosyne/ tests/
All checks passed!

mypy --ignore-missing-imports mnemosyne/
Success: no issues found in 35 source files
```

## Risks

| Risk ID | Risk | Mitigation |
|---|---|---|
| RISK-001 | Timestamp string shape changes could affect downstream users or stored data expectations | Use DEC-WARN-001 Option A for this SPEC |
| RISK-002 | Warning-as-error may expose unrelated third-party warnings later | Scope QG-005 initially to affected tests and project-owned warnings |
| RISK-003 | Helper location could become unnecessary abstraction | Keep helper tiny and only for repeated current UTC ISO usage |
| RISK-004 | Tests may assert exact timestamp format indirectly | Add parseability/shape assertions and avoid wall-clock equality |

## Open Questions

| ID | Question | Default |
|---|---|---|
| OQ-001 | Should this SPEC preserve naive UTC strings or migrate to offset-aware strings? | Preserve naive UTC strings for minimal behavior change |
| OQ-002 | Should QG-005 become part of every pre-commit run immediately? | Add as documented gate; promote to blocking after implementation proves stable |

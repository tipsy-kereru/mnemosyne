---
id: SPEC-WIKI-005
version: "0.1.0"
status: completed
created: "2026-05-03 08:35:34 NZST"
updated: "2026-05-03 09:04:00 NZST"
author: Moon Cell Harness
priority: high
risk: medium
owner_role: Product Architect / CLI Designer
reviewer_role: Security Reviewer / Test Architect
implementation_role: Implementer
source_of_truth: .moon-cell/specs/SPEC-WIKI-005.md
related_backlog: "SPEC-WIKI-003 deferred follow-up: no CLI mutation command for conflict resolution metadata"
---

# SPEC-WIKI-005: Conflict Resolution Review UX and CLI

Generated: 2026-05-03 08:35:34 NZST
Updated: 2026-05-03 09:04:00 NZST

Canonical location: `.moon-cell/specs/SPEC-WIKI-005.md`.

## Status

| Field | Value |
|---|---|
| Stage | Completed |
| Implementation started | 2026-05-03 09:04:00 NZST |
| Implementation completed | 2026-05-03 09:04:00 NZST |
| Promotion gate | Promoted by `$moon-cell run SPEC-WIKI-005` |
| Source evidence | SPEC-WIKI-003 deferred follow-up: no CLI mutation command for conflict resolution metadata |

## Problem Statement

SPEC-WIKI-003 surfaces unresolved conflict metadata, but users still need to edit stored JSON or upstream sources to mark a contradiction as reviewed. Without a safe review UX, unresolved warnings can become noisy and teams may bypass the signal instead of preserving an auditable resolution trail.

## Goals

| ID | Goal |
|---|---|
| G-005-001 | Add a deterministic CLI review workflow for changing conflict resolution metadata without deleting evidence. |
| G-005-002 | Preserve existing and incoming values, source attribution, timestamps, and entity history. |
| G-005-003 | Make lint/status distinguish unresolved, resolved, and ambiguous review states clearly. |
| G-005-004 | Keep the first implementation local-first and dependency-free. |

## Non-Goals

| ID | Non-Goal |
|---|---|
| NG-005-001 | Do not auto-resolve contradictions. |
| NG-005-002 | Do not delete or overwrite source evidence. |
| NG-005-003 | Do not add a network or remote LLM dependency. |
| NG-005-004 | Do not build a full TUI or web UI in the first pass. |

## Requirements

### REQ-WIKI-005-001: List unresolved contradictions

**EARS:** When users inspect wiki contradictions, the system shall list unresolved conflicts with entity ID, property, current values, source, and stable conflict identifiers.
### REQ-WIKI-005-002: Set resolution metadata

**EARS:** When users mark a conflict reviewed, the system shall update only resolution metadata and reviewer notes while preserving stored evidence.
### REQ-WIKI-005-003: Audit trail

**EARS:** When conflict resolution metadata changes, the system shall record graph history or equivalent audit evidence.
### REQ-WIKI-005-004: Status/lint integration

**EARS:** When conflicts are resolved or ambiguous, status and lint shall report them separately from unresolved blockers.
### REQ-WIKI-005-005: Dry-run and JSON output

**EARS:** When resolution commands are used in automation, dry-run and JSON output shall be available for safe review.

## Risks

| Risk ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-WIKI-005-001 | Accidental evidence loss | High | Only mutate metadata fields; add regression tests that source values remain unchanged. |
| R-WIKI-005-002 | Reviewer identity privacy | Medium | Make reviewer fields optional and avoid collecting OS/user identity by default. |
| R-WIKI-005-003 | Ambiguous conflict addressing | Medium | Generate stable conflict IDs from entity/property/source/value hashes. |

## Suggested Task Breakdown

| Task ID | Owner Role | Description | Verification |
|---|---|---|---|
| SPEC-WIKI-005-T1 | Product Architect / CLI Designer | Finalize design and acceptance criteria | SPEC reviewed against source evidence |
| SPEC-WIKI-005-T2 | Security Reviewer / Test Architect | Review safety, compatibility, and test strategy | Risks and non-goals confirmed |
| SPEC-WIKI-005-T3 | Implementer | Implement only after candidate is promoted to planned | Quality gate evidence attached |
| SPEC-WIKI-005-T4 | Test Architect | Add regression and CLI/fixture coverage | Focused tests and static checks pass |

## Verification Commands

- `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q`
- `ruff check mnemosyne tests`
- `mypy mnemosyne`
- `git diff --check`

## Definition of Done

| ID | Check | Required Result |
|---|---|---|
| DOD-SPEC-WIKI-005-001 | Scope | Requirements implemented without exceeding non-goals |
| DOD-SPEC-WIKI-005-002 | Tests | Focused tests pass or documented as not applicable for planning-only work |
| DOD-SPEC-WIKI-005-003 | Static checks | ruff, mypy, and diff hygiene pass when code changes are made |
| DOD-SPEC-WIKI-005-004 | Docs/harness | Manifest, task routing, changelog, and handoff updated |

## Notes

## Implementation Result

Completed: 2026-05-03 09:04:00 NZST

| Requirement | Result | Evidence |
|---|---|---|
| REQ-WIKI-005-001 | PASS | `mnemosyne wiki contradictions` lists unresolved conflicts with stable `conflict_id` values |
| REQ-WIKI-005-002 | PASS | `mnemosyne wiki resolve` updates `resolution`, `reviewed_at`, optional `review_note`, and optional `reviewer` while preserving evidence values |
| REQ-WIKI-005-003 | PASS | Resolution writes call `KnowledgeGraph.update_entity()`, producing entity history version records |
| REQ-WIKI-005-004 | PASS | Status resolution counts and unresolved-only lint warnings distinguish open from resolved/ambiguous conflicts |
| REQ-WIKI-005-005 | PASS | Resolve supports `--dry-run`; contradiction and resolve commands support JSON output |

## Verification Evidence

| Check | Result |
|---|---|
| Focused wiki/ingest/CLI tests | `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` → 81 passed |
| Full pytest | `pytest -q` → 461 passed |
| Static checks | `ruff check mnemosyne tests` clean; `mypy mnemosyne` success across 37 source files |
| CLI smoke | `mnemosyne wiki rebuild/contradictions/resolve --format json` passed against temp DB/wiki roots |

Candidate status was promoted by explicit user command `$moon-cell run SPEC-WIKI-005`.

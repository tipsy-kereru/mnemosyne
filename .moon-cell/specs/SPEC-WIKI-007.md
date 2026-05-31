---
id: SPEC-WIKI-007
version: "0.1.0"
status: completed
created: "2026-05-03 08:35:34 NZST"
updated: "2026-05-03 16:38:24 NZST"
author: Moon Cell Harness
priority: medium
risk: high
owner_role: Data Lifecycle Architect
reviewer_role: Safety Reviewer / Test Architect
implementation_role: Implementer
source_of_truth: .moon-cell/specs/SPEC-WIKI-007.md
related_backlog: "SPEC-WIKI-001 RISK-WIKI-004: deletion/pruning is deferred"
---

# SPEC-WIKI-007: Wiki Prune, Stale Marker, and Tombstone Reconciliation

Generated: 2026-05-03 08:35:34 NZST
Updated: 2026-05-03 16:38:24 NZST

Canonical location: `.moon-cell/specs/SPEC-WIKI-007.md`.

## Status

| Field | Value |
|---|---|
| Stage | Completed |
| Implementation started | 2026-05-03 16:38:24 NZST |
| Implementation completed | 2026-05-03 16:38:24 NZST |
| Promotion gate | Promoted by `$moon-cell run SPEC-WIKI-007` |
| Source evidence | SPEC-WIKI-001 RISK-WIKI-004: deletion/pruning is deferred |

## Problem Statement

Raw source removal or graph changes can leave old wiki pages and graph facts visible indefinitely. Destructive pruning is risky, but the system needs a safe lifecycle model that can mark stale pages/facts, preview deletions, and preserve tombstones before any irreversible cleanup.

## Goals

| ID | Goal |
|---|---|
| G-007-001 | Define non-destructive stale markers and tombstones for graph/wiki reconciliation. |
| G-007-002 | Add dry-run prune planning that reports candidate stale pages and facts without deleting by default. |
| G-007-003 | Preserve manual notes and audit history before any cleanup operation. |
| G-007-004 | Make stale state visible in wiki status/lint outputs. |

## Non-Goals

| ID | Non-Goal |
|---|---|
| NG-007-001 | Do not delete wiki pages or graph facts by default. |
| NG-007-002 | Do not infer that missing raw files mean knowledge is false. |
| NG-007-003 | Do not remove manual notes automatically. |
| NG-007-004 | Do not couple pruning to editor-specific APIs. |

## Requirements

### REQ-WIKI-007-001: Stale detection

**EARS:** When sources disappear or are no longer referenced, the system shall identify affected pages/facts as stale candidates.
### REQ-WIKI-007-002: Dry-run plan

**EARS:** When users request pruning, the first output shall be a dry-run plan with paths, entities, reasons, and risk labels.
### REQ-WIKI-007-003: Tombstone preservation

**EARS:** When cleanup is approved, the system shall preserve tombstone metadata and manual-note recovery paths.
### REQ-WIKI-007-004: Lint/status signal

**EARS:** When stale candidates exist, wiki status/lint shall expose counts and warnings without failing by default.
### REQ-WIKI-007-005: Recovery tests

**EARS:** Regression tests shall prove manual notes are not silently lost.

## Risks

| Risk ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-WIKI-007-001 | Data loss | High | Require dry-run first and tombstones before destructive deletion. |
| R-WIKI-007-002 | False stale positives | Medium | Use explicit source references and require user confirmation for cleanup. |
| R-WIKI-007-003 | Manual note loss | High | Archive or preserve notes outside generated markers before moving/removing pages. |

## Suggested Task Breakdown

| Task ID | Owner Role | Description | Verification |
|---|---|---|---|
| SPEC-WIKI-007-T1 | Data Lifecycle Architect | Finalize design and acceptance criteria | SPEC reviewed against source evidence |
| SPEC-WIKI-007-T2 | Safety Reviewer / Test Architect | Review safety, compatibility, and test strategy | Risks and non-goals confirmed |
| SPEC-WIKI-007-T3 | Implementer | Implement only after candidate is promoted to planned | Quality gate evidence attached |
| SPEC-WIKI-007-T4 | Test Architect | Add regression and CLI/fixture coverage | Focused tests and static checks pass |

## Verification Commands

- `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py --tb=short -q`
- `git diff --check`
- `manual dry-run smoke with temp wiki/db`

## Definition of Done

| ID | Check | Required Result |
|---|---|---|
| DOD-SPEC-WIKI-007-001 | Scope | Requirements implemented without exceeding non-goals |
| DOD-SPEC-WIKI-007-002 | Tests | Focused tests pass or documented as not applicable for planning-only work |
| DOD-SPEC-WIKI-007-003 | Static checks | ruff, mypy, and diff hygiene pass when code changes are made |
| DOD-SPEC-WIKI-007-004 | Docs/harness | Manifest, task routing, changelog, and handoff updated |

## Notes

## Implementation Result

Completed: 2026-05-03 16:38:24 NZST

| Requirement | Result | Evidence |
|---|---|---|
| REQ-WIKI-007-001 | PASS | `LLMWikiMaintainer.stale_plan()` detects orphan entity/source pages and missing local raw-source references |
| REQ-WIKI-007-002 | PASS | `mnemosyne wiki prune --format json` returns dry-run plans with paths, entity/source IDs, reasons, risk labels, and manual-note previews |
| REQ-WIKI-007-003 | PASS | `mnemosyne wiki prune --apply-tombstones` writes Markdown tombstones under `tombstones/` and performs zero deletes |
| REQ-WIKI-007-004 | PASS | `status()` includes stale counts and `lint()` emits non-blocking `stale-candidate` warnings |
| REQ-WIKI-007-005 | PASS | Regression tests assert manual notes remain in original pages and tombstone previews |

## Verification Evidence

| Check | Result |
|---|---|
| Focused wiki/ingest/CLI tests | `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` → 83 passed |
| Full pytest | `pytest -q` → 463 passed |
| Static checks | `ruff check mnemosyne tests` clean; `mypy mnemosyne` success across 37 source files |
| CLI smoke | `mnemosyne wiki rebuild/prune --format json` and `prune --apply-tombstones` passed against temp DB/wiki roots |

Candidate status was promoted by explicit user command `$moon-cell run SPEC-WIKI-007`.

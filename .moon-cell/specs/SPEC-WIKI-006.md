---
id: SPEC-WIKI-006
version: "0.1.0"
status: completed
created: "2026-05-03 08:35:34 NZST"
updated: "2026-05-03 17:31:31 NZST"
author: Moon Cell Harness
priority: medium
risk: high
owner_role: Solution Architect / AI Safety Reviewer
reviewer_role: Security Reviewer / Product Reviewer
implementation_role: Implementer
source_of_truth: .moon-cell/specs/SPEC-WIKI-006.md
related_backlog: "SPEC-WIKI-001 FUTURE-WIKI-002 and SPEC-WIKI-003 non-goal: no semantic/LLM contradiction claims"
---

# SPEC-WIKI-006: Optional Semantic Contradiction Discovery

Generated: 2026-05-03 08:35:34 NZST
Updated: 2026-05-03 17:31:31 NZST

Canonical location: `.moon-cell/specs/SPEC-WIKI-006.md`.

## Status

| Field | Value |
|---|---|
| Stage | Completed |
| Implementation started | 2026-05-03 17:31:31 NZST |
| Implementation completed | 2026-05-03 17:31:31 NZST |
| Source evidence | SPEC-WIKI-001 FUTURE-WIKI-002 and SPEC-WIKI-003 non-goal: no semantic/LLM contradiction claims |

## Problem Statement

The current contradiction layer only surfaces exact property conflicts already stored in graph metadata. It cannot identify semantic conflicts such as two notes describing incompatible dates, responsibilities, or statuses in different phrasing. Adding semantic discovery may be useful, but it introduces false-certainty, privacy, and provenance risks.

## Goals

| ID | Goal |
|---|---|
| G-006-001 | Design an opt-in semantic contradiction discovery pipeline that produces review candidates, not truth judgments. |
| G-006-002 | Support an offline/local-first baseline before any remote model integration. |
| G-006-003 | Require source snippets, confidence, rationale, and explicit uncertainty labels for every candidate. |
| G-006-004 | Keep deterministic metadata conflicts separate from semantic/LLM candidates in status, lint, and wiki pages. |

## Non-Goals

| ID | Non-Goal |
|---|---|
| NG-006-001 | Do not enable remote LLM calls by default. |
| NG-006-002 | Do not fail lint on semantic candidates unless explicitly configured. |
| NG-006-003 | Do not merge or delete graph facts based on semantic candidates. |
| NG-006-004 | Do not summarize sensitive raw text without redaction and explicit opt-in. |

## Requirements

### REQ-WIKI-006-001: Candidate schema

**EARS:** When semantic contradictions are detected, the system shall store candidates in a distinct schema from deterministic property conflicts.
### REQ-WIKI-006-002: Opt-in execution

**EARS:** When users run semantic discovery, it shall require an explicit command/config flag and disclose model/local processing mode.
### REQ-WIKI-006-003: Evidence-first output

**EARS:** When a candidate is shown, it shall include source references, bounded excerpts, confidence, uncertainty wording, and generated-at metadata.
### REQ-WIKI-006-004: Safety boundaries

**EARS:** When raw text contains sensitive patterns, excerpts shall be redacted or omitted according to wiki privacy policy.
### REQ-WIKI-006-005: Evaluation set

**EARS:** Before implementation is considered complete, tests/fixtures shall cover false-positive and true-positive examples.

## Risks

| Risk ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-WIKI-006-001 | False certainty | High | Use review-candidate wording and keep lint non-blocking by default. |
| R-WIKI-006-002 | Privacy leakage | High | Default to offline/no excerpts; require explicit opt-in for remote providers. |
| R-WIKI-006-003 | Unstable model outputs | Medium | Persist model/config metadata and validate deterministic schema shape. |

## Suggested Task Breakdown

| Task ID | Owner Role | Description | Verification |
|---|---|---|---|
| SPEC-WIKI-006-T1 | Solution Architect / AI Safety Reviewer | Finalize design and acceptance criteria | SPEC reviewed against source evidence |
| SPEC-WIKI-006-T2 | Security Reviewer / Product Reviewer | Review safety, compatibility, and test strategy | Risks and non-goals confirmed |
| SPEC-WIKI-006-T3 | Implementer | Implement only after candidate is promoted to planned | Quality gate evidence attached |
| SPEC-WIKI-006-T4 | Test Architect | Add regression and CLI/fixture coverage | Focused tests and static checks pass |

## Verification Commands

- `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py --tb=short -q`
- `ruff check mnemosyne tests`
- `mypy mnemosyne`
- `manual privacy review of generated fixtures`

## Definition of Done

| ID | Check | Required Result |
|---|---|---|
| DOD-SPEC-WIKI-006-001 | Scope | Requirements implemented without exceeding non-goals |
| DOD-SPEC-WIKI-006-002 | Tests | Focused tests pass or documented as not applicable for planning-only work |
| DOD-SPEC-WIKI-006-003 | Static checks | ruff, mypy, and diff hygiene pass when code changes are made |
| DOD-SPEC-WIKI-006-004 | Docs/harness | Manifest, task routing, changelog, and handoff updated |

## Notes

This is a candidate SPEC. It is intentionally not implementation approval by itself.

## Implementation Result

SPEC-WIKI-006 is implemented as an explicit local/offline semantic review lane.
The implementation intentionally avoids remote model calls, graph fact mutation,
and truth-judgment wording. Candidates are persisted only when the user passes
`--write`.

| Requirement | Result | Evidence |
|---|---|---|
| REQ-WIKI-006-001 | Implemented | `review/semantic-contradictions.json` uses schema `mnemosyne.semantic_contradiction_candidates.v1`, separate from deterministic `properties["conflicts"]`. |
| REQ-WIKI-006-002 | Implemented | `mnemosyne wiki semantic-contradictions` is an explicit command and payload discloses `processing_mode: local-offline`, `remote_model: false`. |
| REQ-WIKI-006-003 | Implemented | Candidates include source references, bounded redacted excerpts, confidence, uncertainty wording, rationale, and generated-at metadata. |
| REQ-WIKI-006-004 | Implemented | Evidence uses existing redaction helpers; raw source excerpts require `--include-raw-excerpts`. |
| REQ-WIKI-006-005 | Implemented | Regression fixtures cover true-positive status/responsibility examples and false-positive same-status examples. |

## Verification Evidence

| Check | Result |
|---|---|
| Focused wiki/ingest/CLI tests | `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` → 85 passed |
| Full pytest | `python -m pytest -q` → 465 passed |
| Ruff | `ruff check mnemosyne tests` → 0 violations |
| Mypy | `mypy mnemosyne` → 0 errors across 37 source files |
| Diff hygiene | `git diff --check` and `git diff --cached --check` passed |

## Safety Notes

- Semantic candidates are review candidates only and are not lint errors unless
  users opt into strict warning failure.
- Discovery does not resolve deterministic conflicts, merge facts, delete facts,
  or delete wiki pages.
- Remote providers remain out of scope for this SPEC.

---
id: SPEC-HARNESS-001
version: "1.0.0"
status: completed
created: "2026-05-03 08:35:34 NZST"
updated: "2026-05-04 13:28:55 NZST"
author: Moon Cell Harness
priority: low
risk: low-medium
owner_role: Harness Engineer
reviewer_role: Repository Maintainer
implementation_role: Harness Writer
source_of_truth: .moon-cell/specs/SPEC-HARNESS-001.md
related_backlog: "FUTURE-003 optional root AGENTS.md Moon Cell bridge and repeated force-add handling for ignored .moon-cell files"
---

# SPEC-HARNESS-001: Root Bridge and Moon Cell Tracking Policy

Generated: 2026-05-03 08:35:34 NZST
Updated: 2026-05-03 08:35:34 NZST

Canonical location: `.moon-cell/specs/SPEC-HARNESS-001.md`.

## Status

| Field | Value |
|---|---|
| Stage | Completed — 2026-05-04 |
| Tracking policy | Option B: `!.moon-cell/` exception in `.gitignore` |
| Root bridge | Option Y: Moon Cell pointer section added to `AGENTS.md` |
| Approved by | User (explicit selection 2026-05-04) |

## Problem Statement

Moon Cell artifacts are currently the source of truth but remain ignored by `.gitignore`, requiring repeated `git add -f .moon-cell`. Root bridge files are intentionally untouched without explicit confirmation. A small harness policy SPEC can decide whether to keep force-add, revise ignore rules, or add a short root bridge.

## Goals

| ID | Goal |
|---|---|
| G-001-001 | Document the repository policy for tracking `.moon-cell/` artifacts. |
| G-001-002 | Decide whether a short root AGENTS.md or CLAUDE.md bridge is desirable. |
| G-001-003 | Avoid weakening local scratch ignores or overwriting existing root guidance. |
| G-001-004 | Keep the policy reversible and explicit. |

## Non-Goals

| ID | Non-Goal |
|---|---|
| NG-001-001 | Do not edit root bridge files without explicit user approval. |
| NG-001-002 | Do not delete existing harness artifacts. |
| NG-001-003 | Do not change product behavior. |

## Requirements

### REQ-HARNESS-001-001: Tracking policy

**EARS:** The SPEC shall compare force-add, .gitignore exception, and split tracked/untracked harness state options.
### REQ-HARNESS-001-002: Bridge decision

**EARS:** The SPEC shall define whether root AGENTS.md/CLAUDE.md should point to `.moon-cell/` or remain unchanged.
### REQ-HARNESS-001-003: Safety gate

**EARS:** Any root bridge or ignore change shall require explicit approval and diff review.

## Risks

| Risk ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-HARNESS-001-001 | Accidental local state tracking | Medium | Prefer narrow .gitignore exceptions if policy changes. |
| R-HARNESS-001-002 | Instruction conflict | Medium | Keep root bridge short and subordinate to existing AGENTS.md instructions. |

## Suggested Task Breakdown

| Task ID | Owner Role | Description | Verification |
|---|---|---|---|
| SPEC-HARNESS-001-T1 | Harness Engineer | Finalize design and acceptance criteria | SPEC reviewed against source evidence |
| SPEC-HARNESS-001-T2 | Repository Maintainer | Review safety, compatibility, and test strategy | Risks and non-goals confirmed |
| SPEC-HARNESS-001-T3 | Harness Writer | Implement only after candidate is promoted to planned | Quality gate evidence attached |
| SPEC-HARNESS-001-T4 | Test Architect | Add regression and CLI/fixture coverage | Focused tests and static checks pass |

## Verification Commands

- `git status --short confirms intended tracked files only`
- `git diff --check`
- `manual approval recorded before root/ignore changes`

## Definition of Done

| ID | Check | Required Result |
|---|---|---|
| DOD-SPEC-HARNESS-001-001 | Scope | Requirements implemented without exceeding non-goals |
| DOD-SPEC-HARNESS-001-002 | Tests | Focused tests pass or documented as not applicable for planning-only work |
| DOD-SPEC-HARNESS-001-003 | Static checks | ruff, mypy, and diff hygiene pass when code changes are made |
| DOD-SPEC-HARNESS-001-004 | Docs/harness | Manifest, task routing, changelog, and handoff updated |

## Notes

This is a candidate SPEC. It is intentionally not implementation approval by itself.

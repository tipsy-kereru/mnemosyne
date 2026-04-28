# Agent Team Blueprint

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-28 18:43:18 NZST

## Source Inputs

| Artifact | Status | Notes |
|---|---|---|
| .moai/specs/SPEC-*/spec.md | Present (6 completed) | All requirements implemented |
| .moon-cell/docs/harness/QUALITY_GATES.md | Present | QG-001 through QG-003 |
| .moon-cell/docs/harness/MODEL_ROUTING.md | Present | 3 model classes |
| .moon-cell/docs/harness/SKILL_INVENTORY.md | Present | 7 tools + 6 MoAI skills |

## Team Summary

| Role | Responsibility | Pattern Provider | Capability Source | Runtime Form | Model Class | Output |
|---|---|---|---|---|---|---|
| Architect | SPEC design, architecture decisions | MoAI-ADK | CLAUDE.md, SPEC docs | Sub-agent (expert-backend) | reasoning-heavy | SPEC doc, decision log |
| Implementer | Code changes, TDD cycle | MoAI-ADK | mnemosyne/, tests/ | Sub-agent (manager-tdd) | implementation | Code + tests |
| Reviewer | Quality gate, diff review | MoAI-ADK | ruff, mypy, pytest | Sub-agent (evaluator-active) | reasoning-heavy | Review report |
| Doc Writer | CHANGELOG, SPEC status, handoff | MoAI-ADK | CHANGELOG.md, SPEC docs | Sub-agent (manager-docs) | cheap-fast | Updated docs |

## Runtime Bridge Notes

| Runtime | Supported Form | Status | Fallback |
|---|---|---|---|
| Claude Code | Sub-agent via Agent() tool | Verified | Sequential role prompt |

## Approval Gates

| Gate | Required Before | Approver |
|---|---|---|
| G-ARCH | Architecture or multi-file change | User |
| G-SPEC | New SPEC creation | User |
| G-DESTRUCT | Destructive operations | User |
| G-RELEASE | Version bump or PR | User |

## Open Questions

None. All 6 SPECs completed. Future feature development will generate new SPECs.

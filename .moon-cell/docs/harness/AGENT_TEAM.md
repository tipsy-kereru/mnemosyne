# Agent Team Blueprint

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-29 09:50:42 NZST

Moon Cell defines this team in vendor-neutral terms. Runtime bridges translate it into product-specific subagents, tasks, skills, role prompts, or sequential checklists.

## Source Inputs

| Artifact | Status | Notes |
|---|---|---|
| .moai/specs/SPEC-*/spec.md | Present | 8 product/quality SPECs completed; SPEC-RENAME-001 also completed |
| .moon-cell/docs/harness/QUALITY_GATES.md | Present | QG-001 through QG-004 |
| .moon-cell/docs/harness/MODEL_ROUTING.md | Present | 3 model classes with Claude and Codex bridge maps |
| .moon-cell/docs/harness/SKILL_INVENTORY.md | Present | Project tools, MCP servers, MoAI skills, OMX/Codex skills summarized |
| README.md | Present | Current quality summary: 413 passed, 2 skipped, 8 completed SPECs |

## Responsibility Split

| Layer | Responsibility |
|---|---|
| Moon Cell | Orchestration designer and team blueprint owner |
| MoAI-ADK-like patterns | SPEC-first structure, task IDs, acceptance criteria, tests, traceability |
| gstack-like patterns | Product, engineering, design, DX, QA, security, release, retrospective review loops |
| ECC-like patterns | Cross-harness operations, reusable skills, memory/context continuity, verification loops, permission profiles |
| Runtime | Actual execution engine: subagents, tasks, skills, prompts, MCP calls, or sequential checklists |

## Team Summary

| Role | Responsibility | Pattern Provider | Capability Source | Runtime Form | Model Class | Output |
|---|---|---|---|---|---|---|
| Product Strategist | Clarify users, outcomes, non-goals, and success metrics when product intent is ambiguous | gstack-like | README, PRD/SPEC docs | Role prompt / subagent when available | reasoning-heavy | Scope decisions, open questions |
| Spec Architect | Convert approved work into SPEC IDs, requirements, acceptance criteria, and traceability | MoAI-ADK-like | `.moai/specs/**`, `.moon-cell/docs/**` | Role prompt / subagent when available | reasoning-heavy | SPEC updates, task matrix |
| Solution Architect | Review architecture, APIs, data flow, graph schema, extraction pipeline, and migration risks | gstack-like / MoAI-ADK-like | Source tree, docs, tests, LSP when available | Role prompt / subagent when available | reasoning-heavy | Architecture notes, risk list |
| Implementer | Make bounded code/test/doc changes after scope is clear | MoAI-ADK-like / ECC-like | Runtime tools, pytest, ruff, mypy | Main agent or bounded subagent | implementation | Code, tests, docs |
| Test Architect | Define regression tests, edge cases, coverage strategy, and quality evidence | MoAI-ADK-like / gstack-like | pytest, pytest-cov, jest | Role prompt / subagent when available | implementation | Test plan and verification evidence |
| Reviewer | Independently review diffs, generated harness docs, and quality claims | gstack-like / ECC-like | Diff, quality outputs, harness docs | Review pass / subagent when useful | reasoning-heavy | Findings and required fixes |
| Security Reviewer | Review secret handling, private data, MCP trust boundaries, or regulated-domain logic | ECC-like / gstack-like | Security tools only when permitted | Role prompt / subagent when needed | reasoning-heavy | Security notes and gates |
| Handoff Writer | Preserve session continuity and summarize decisions, files, commands, and risks | ECC-like | `CONTEXT_HANDOFF.md`, changelog | Main-agent checklist | cheap-fast | Updated handoff |

## Runtime Bridge Notes

| Runtime | Supported Form | Status / Evidence | Fallback |
|---|---|---|---|
| Claude Code | Subagent / skill / prompt if supported | Existing root `CLAUDE.md` and `.moon-cell/bridges/claude-code/MODEL_MAP.md`; model aliases should be verified before use | Sequential role prompt |
| Codex App / Codex CLI | Native subagents, skills, AGENTS.md-style guidance, shell tools | Current session confirms Codex App surface and available skills; bridge added at `.moon-cell/bridges/codex/MODEL_MAP.md` | Main-agent sequential role prompts |
| Cursor-like | Rules/skills/background agent if configured | Unknown; no Cursor bridge created | Sequential role prompt |
| Gemini-like / Other | Prompt/workflow file if configured | Unknown; no Gemini bridge created | Sequential role prompt |

## Approval Gates

| Gate | Required Before | Approver |
|---|---|---|
| G-ARCH | Architecture, database schema, public API, or multi-file design change | User |
| G-SPEC | New SPEC creation or scope expansion | User |
| G-DESTRUCT | Destructive operations | User |
| G-RELEASE | Version bump, publishing, PR, or deploy | User |
| G-SECURITY | Secrets, private data, regulated-domain decisions | User |
| G-BRIDGE | Root/runtime bridge files outside `.moon-cell/` | User |

## Sequential Fallback

When subagents are unavailable or unnecessary, execute roles in this order:

1. Spec Architect or Product Strategist for unclear requirements.
2. Solution Architect for architecture or migration risk.
3. Implementer for bounded code/test/doc edits.
4. Test Architect for verification strategy and edge cases.
5. Reviewer for diff and claim validation.
6. Handoff Writer for continuity artifacts.

## Open Questions

| ID | Question | Impact |
|---|---|---|
| OQ-001 | Should root `AGENTS.md` become a short Moon Cell bridge in a future update? | Optional; requires explicit confirmation |
| OQ-002 | Should timezone-aware datetime warnings become a new SPEC? | Optional quality improvement |
| OQ-003 | Should async I/O remain deferred or become a planned SPEC? | Optional architecture improvement |

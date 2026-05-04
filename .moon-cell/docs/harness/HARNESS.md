# Project Harness

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-29 09:50:42 NZST

Canonical location: `.moon-cell/docs/harness/HARNESS.md`.

## Purpose

Mnemosyne Knowledge Graph is a local-first, zero-API-cost knowledge memory system for AI agents. It provides persistent, compounding knowledge across daily life, coding, and legal domains using a raw-source layer, markdown wiki layer, schema guidance, and SQLite/NetworkX graph storage.

## Source of Truth

| Artifact | Location | Status | Evidence |
|---|---|---|---|
| SPEC documents | `.moai/specs/SPEC-*/spec.md` | 8 completed product/quality SPECs plus completed rename SPEC | Inspected 2026-04-29 |
| Source code | `mnemosyne/` | Python package source | `pyproject.toml` package include `mnemosyne*` |
| Tests | `tests/` | 413 passed, 2 skipped | `python3 -m pytest --tb=short -q` on 2026-04-29 |
| Package config | `pyproject.toml` | `mnemosyne-kg`, Python >=3.11 | Inspected 2026-04-29 |
| Joplin plugin | `joplin-plugin/knowledge-graph/` | TypeScript/Jest plugin workspace | `package.json` present |
| Runtime bridges | `.moon-cell/bridges/` | Claude Code retained; Codex bridge added | Safe refresh 2026-04-29 |

## Workflow

1. **Change proposal**: Identify scope via SPEC reference, README capability, or natural-language task.
2. **Audit check**: Inspect current code and docs before editing; prefer existing utilities and patterns.
3. **Planning gate**: Create or update a SPEC for major architecture, data model, public API, or multi-session work.
4. **Implementation**: Use small, reversible edits. Prefer TDD for new behavior and regression tests for fixes.
5. **Quality gate**: Run the relevant commands from `QUALITY_GATES.md` before declaring completion.
6. **Documentation sync**: Update README, CHANGELOG, SPEC status, and harness docs when project state changes.
7. **Handoff**: Update `CONTEXT_HANDOFF.md` for significant work or before context transfer.

## Human Confirmation Gates

| Gate | When | Approver |
|---|---|---|
| G-ARCH | Architecture, database schema, public API, or multi-file design change | User |
| G-SPEC | New SPEC creation, scope expansion, or acceptance criteria change | User |
| G-DESTRUCT | Deleting files, destructive git operations, database migration, or irreversible cleanup | User |
| G-RELEASE | Version bump, package publishing, PR creation, or deployment | User |
| G-SECURITY | Secret/credential handling, private data exposure, or security-sensitive change | User |
| G-BRIDGE | Creating or modifying root/runtime bridge files outside `.moon-cell/` | User |

## Agent Roles

| Role | Use When | Model Class | Runtime Form |
|---|---|---|---|
| Product Strategist | Value, users, non-goals, or success criteria are unclear | reasoning-heavy | Role prompt / subagent when available |
| Spec Architect | Requirements need SPEC IDs, acceptance criteria, task routing, or traceability | reasoning-heavy | Role prompt / subagent when available |
| Solution Architect | Architecture, API, data flow, migration, or integration decisions are needed | reasoning-heavy | Role prompt / subagent when available |
| Implementer | Confirmed code, tests, refactors, and bug fixes | implementation | Main agent or bounded subagent |
| Test Architect | Regression strategy, coverage gaps, edge cases, or flaky tests | implementation | Role prompt / subagent when available |
| Reviewer | Diff review, quality gate review, release readiness | reasoning-heavy | Independent review pass |
| Handoff Writer | Session continuity, changelog, context transfer | cheap-fast | Main agent checklist |

## Skill and Tool Routing

| Capability | Tool / Source | Trust Level | Recommended Use |
|---|---|---|---|
| Python tests | pytest | High | Regression and acceptance verification |
| Python lint | ruff | High | Style/static lint gate |
| Python type check | mypy | High | Type-safety gate |
| Coverage | pytest-cov | High | Coverage warning threshold |
| JavaScript plugin tests | jest | High | Joplin plugin verification |
| Code parsing | tree-sitter optional deps | Medium | Deterministic extraction feature work |
| Graph storage | SQLite + NetworkX | High | Knowledge graph persistence and traversal |
| MCP documentation lookup | context7 | Medium | Version-aware docs when available |
| MCP reasoning aid | sequential-thinking | Medium | Complex planning only when useful |
| MCP code intelligence | moai-lsp | Medium | LSP navigation if server is available |

## Agent Team

See `.moon-cell/docs/harness/AGENT_TEAM.md` for the vendor-neutral blueprint and runtime bridge notes.

## Task Routing

See `.moon-cell/docs/harness/TASK_ROUTING.md` for completed SPECs, backlog blockers, and recommended role ownership.

## Model Routing

See `.moon-cell/docs/harness/MODEL_ROUTING.md` and runtime-specific maps under `.moon-cell/bridges/`.

## Implementation Guardrails

1. State assumptions when they affect design or test scope.
2. Choose the simplest approach that satisfies the requirement.
3. Identify target files before editing.
4. Lock existing behavior with tests before cleanup/refactor work when coverage is uncertain.
5. Keep diffs small, reviewable, and reversible.
6. Reuse existing utilities and patterns before adding abstractions.
7. Run relevant quality gates and read outputs before claiming completion.
8. Review the diff for unrelated changes, stale docs, and speculative abstraction.
9. Do not modify root bridge files (`AGENTS.md`, `CLAUDE.md`, Cursor rules, etc.) without explicit confirmation.

## Quality Gates

See `.moon-cell/docs/harness/QUALITY_GATES.md` for full gate definitions.

## Context Handoff Rules

- Update `.moon-cell/docs/harness/CONTEXT_HANDOFF.md` after significant harness, SPEC, release, or architecture work.
- Include decisions made, files changed, commands run, open questions, risks, and next recommended action.
- Keep the handoff concise and evidence-backed.

## Prohibited Actions

- Never inspect or expose secrets, credentials, keychains, browser profiles, or private tokens.
- Never commit secrets or credentials.
- Never force-push to main/master.
- Never run destructive commands without explicit user approval.
- Never publish packages, create PRs, deploy services, or send external messages without explicit approval.
- Never skip quality gates for production changes.

## Next Steps

| Priority | Action | Notes |
|---|---|---|
| P1 | Keep harness metadata synchronized after SPEC or quality status changes | Current refresh completed 2026-04-29 |
| P2 | Consider a future SPEC for timezone-aware datetime migration | Current test warnings show `datetime.utcnow()` deprecations |
| P3 | Consider a future SPEC for async I/O | Deferred blocker from production hardening |

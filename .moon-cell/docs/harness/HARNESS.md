# Project Harness

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-28 18:43:18 NZST

Canonical location: `.moon-cell/docs/harness/HARNESS.md`.

## Purpose

Mnemosyne Knowledge Graph is a local-first, zero-API-cost knowledge memory system for AI agents. It provides persistent, compounding knowledge across three domains: daily life, coding, and legal. Based on Google's Gemini Universal Temporal Knowledge Graph research.

## Source of Truth

| Artifact | Location | Status |
|---|---|---|
| SPEC documents | `.moai/specs/SPEC-*/spec.md` | 6/6 completed |
| Source code | `mnemosyne/` | 28 Python files |
| Tests | `tests/` | 295 passed, 2 skipped |
| Package config | `pyproject.toml` | v0.1.0 |
| Joplin plugin | `joplin-plugin/` | TypeScript |

## Workflow

1. **Change proposal**: Identify scope via SPEC reference or natural language.
2. **Audit check**: Review current state before change (Karpathy guardrails).
3. **Implementation**: TDD cycle (RED-GREEN-REFACTOR) for new features.
4. **Quality gate**: mypy 0, ruff 0, pytest pass, coverage >= 80%.
5. **Documentation sync**: Update CHANGELOG, SPEC status, relevant docs.
6. **Handoff**: Update CONTEXT_HANDOFF.md before session end.

## Human Confirmation Gates

| Gate | When | Approver |
|---|---|---|
| G-ARCH | Architecture or multi-file change proposed | User |
| G-SPEC | New SPEC creation or scope change | User |
| G-DESTRUCT | Destructive git operations, DB migration | User |
| G-RELEASE | Version bump, PyPI deploy, PR creation | User |
| G-SECURITY | Secret/credential handling, security-sensitive code | User |

## Agent Roles

| Role | Use When | Model Class |
|---|---|---|
| Architect | Architecture decisions, SPEC design | reasoning-heavy |
| Implementer | Code changes, bug fixes, refactoring | implementation |
| Reviewer | Quality gate, code review, diff analysis | reasoning-heavy |
| Tester | Test writing, coverage analysis | implementation |
| Doc Writer | Documentation sync, CHANGELOG updates | cheap-fast |

## Skill and Tool Routing

| Capability | Tool | Trust Level |
|---|---|---|
| Python lint/format | ruff | High |
| Python type check | mypy --ignore-missing-imports | High |
| Python test | pytest | High |
| JS test | jest | High |
| Tree-sitter parsing | py-tree-sitter >= 0.22 | Medium (optional dep) |
| Knowledge graph DB | SQLite via stdlib | High |
| Joplin plugin build | npm | High |

## Implementation Guardrails

1. State assumptions explicitly before coding.
2. Choose the simplest approach that satisfies the requirement.
3. Identify target files before editing.
4. Define verifiable success criteria.
5. Run quality gate before declaring done.
6. Review diff for unrelated changes or speculative abstraction.
7. Touch only what was asked to touch.

## Quality Gates

See `.moon-cell/docs/harness/QUALITY_GATES.md` for full gate definitions.

## Context Handoff Rules

- Update `.moon-cell/docs/harness/CONTEXT_HANDOFF.md` before session end.
- Include: decisions made, files changed, commands run, open questions, next action.
- Keep handoff under 500 lines.

## Prohibited Actions

- Never commit secrets or credentials.
- Never force-push to main/master.
- Never run destructive commands without explicit user approval.
- Never skip quality gates for production changes.

## Next Steps

- Production hardening: logging, type safety, CLI coverage improvements.
- Future SPEC development for new features.
- PyPI packaging and distribution pipeline.

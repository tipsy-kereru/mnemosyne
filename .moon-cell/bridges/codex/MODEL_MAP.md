# Codex Model Map

Generated: 2026-04-29 09:50:42 NZST
Updated: 2026-04-29 09:50:42 NZST

Source of truth: `.moon-cell/docs/harness/MODEL_ROUTING.md`.

This map translates Moon Cell vendor-neutral model classes to Codex runtime guidance observed in the current session metadata. Treat these as project bridge defaults, not global requirements.

| Moon Cell Class | Codex Runtime Guidance | Reasoning Effort | Fallback |
|---|---|---|---|
| reasoning-heavy | `gpt-5.5` | high | inherited frontier/default model |
| implementation | `gpt-5.5` | medium | inherited default model |
| cheap-fast | `gpt-5.3-codex-spark` | low | inherited fast/default model |
| default | inherited session model | session default | system default |

## Role Mapping

| Moon Cell Role | Codex Role / Surface | Model Class |
|---|---|---|
| Product Strategist | `planner` or main-agent role prompt | reasoning-heavy |
| Spec Architect | `architect` / `planner` or main-agent role prompt | reasoning-heavy |
| Solution Architect | `architect` | reasoning-heavy |
| Implementer | `executor` or main agent | implementation |
| Test Architect | `test-engineer` | implementation |
| Reviewer | `code-reviewer` / `verifier` | reasoning-heavy |
| Handoff Writer | `writer` or main-agent checklist | cheap-fast |

## Rules

- Prefer inheriting the active Codex model unless the task has a clear reason to route differently.
- Use subagents only for independent, bounded work where parallelism or specialization improves throughput.
- Keep `.moon-cell/` as source of truth; do not modify root `AGENTS.md` unless explicitly confirmed.
- If this project is run outside Codex, use `MODEL_ROUTING.md` and the relevant runtime bridge instead.

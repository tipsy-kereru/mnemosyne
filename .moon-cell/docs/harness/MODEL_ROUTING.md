# Model Routing

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-29 09:50:42 NZST

Moon Cell uses vendor-neutral model classes internally. Runtime bridges map these classes to concrete runtime aliases or model IDs when those names are known from permitted runtime context.

| Class | Use For | Notes |
|---|---|---|
| reasoning-heavy | Architecture decisions, SPEC design, complex tradeoffs, security/privacy review, high-risk debugging | Strongest reasoning model available in the active runtime |
| implementation | Code implementation, refactoring, tests, bug fixes, build/test debugging | Balanced coding model with tool execution |
| cheap-fast | Documentation, summaries, handoff, inventory, simple read-only exploration | Fast/low-cost model or runtime fast lane |

## Runtime Maps

| Runtime | Map | Status |
|---|---|---|
| Claude Code | `.moon-cell/bridges/claude-code/MODEL_MAP.md` | Existing bridge retained; verify model aliases before relying on them |
| Codex App / Codex CLI | `.moon-cell/bridges/codex/MODEL_MAP.md` | Added 2026-04-29 from current Codex session metadata |

## Runtime Enforcement

- Do not assume a runtime understands Moon Cell classes automatically.
- Use runtime-specific model maps only as bridge guidance, not as a security boundary.
- Prefer runtime aliases or current session-provided model contracts when stable.
- Do not invent model IDs. If a concrete runtime name is unknown, keep `system-default` or `TBD` and ask or inspect permitted runtime configuration.
- For Codex native child agents, prefer role-appropriate reasoning effort and inherited defaults unless a concrete routing reason exists.

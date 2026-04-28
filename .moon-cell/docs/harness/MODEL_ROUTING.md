# Model Routing

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-28 18:43:18 NZST

Moon Cell uses vendor-neutral model classes internally. Runtime bridges map these classes to concrete aliases or model IDs.

| Class | Use For | Notes |
|---|---|---|
| reasoning-heavy | Architecture decisions, SPEC design, security review, complex debugging | Strongest reasoning model available |
| implementation | Code changes, refactoring, tests, bug fixes, build debugging | Balanced coding model |
| cheap-fast | Documentation, summaries, handoff, inventory, read-only exploration | Low-cost fast model |

## Runtime Enforcement
- Do not assume a runtime understands Moon Cell classes automatically.
- Use `.moon-cell/bridges/claude-code/MODEL_MAP.md` for Claude Code mapping.
- Prefer runtime aliases when stable.
- Do not invent model IDs.

# Claude Code Model Map

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-28 18:43:18 NZST

| Moon Cell Class | Claude Code Model | Fallback |
|---|---|---|
| reasoning-heavy | claude-opus-4-7 | claude-sonnet-4-6 |
| implementation | claude-sonnet-4-6 | claude-haiku-4-5 |
| cheap-fast | claude-haiku-4-5 | claude-sonnet-4-6 |
| default | claude-sonnet-4-6 | system default |

## Rules
- Model IDs follow Anthropic naming conventions.
- Claude Code runtime selects model via settings or CLI flags.
- If user has custom model preferences, update this map.

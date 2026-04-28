# Moon Cell Harness Changelog

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-28 18:43:18 NZST

## [0.1.0] - 2026-04-28

### Added
- Initial Moon Cell harness workspace created
- Harness style: Hybrid (Audit-first + SPEC-first lite + Karpathy guardrails)
- VERSION, MANIFEST.md, DOC_STYLE.md created
- HARNESS.md with workflow, confirmation gates, guardrails
- QUALITY_GATES.md with QG-001 (pre-commit), QG-002 (pre-release), QG-003 (architecture)
- MODEL_ROUTING.md with vendor-neutral model classes
- bridges/claude-code/MODEL_MAP.md with Claude Code model mapping
- SKILL_INVENTORY.md with 7 tools, 6 MoAI skills, 5 production gaps
- AGENT_TEAM.md with 4 roles: Architect, Implementer, Reviewer, Doc Writer
- CONTEXT_HANDOFF.md initialized

### Baseline
- 6/6 SPECs completed (SESSION-001, SESSION-002, PKG-001, TS-001, PIPE-001, QUALITY-001)
- 295 tests passing, mypy 0 errors, ruff 0 violations
- Package: mnemosyne-kg v0.1.0, Python 3.11+

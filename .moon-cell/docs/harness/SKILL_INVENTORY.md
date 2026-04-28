# Skill and Tool Inventory

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-28 18:43:18 NZST

## Project Tools

| Capability | Type | Location | Scope | Trust Level | Side Effects | Recommended Use |
|---|---|---|---|---|---|---|
| ruff | CLI linter | pyproject.toml | mnemosyne/, tests/ | High | File modification (--fix) | Lint + format |
| mypy | Type checker | pyproject.toml | mnemosyne/ | High | None | Type safety |
| pytest | Test runner | pyproject.toml | tests/ | High | File creation (--cov) | Test execution |
| jest | JS test runner | joplin-plugin/package.json | joplin-plugin/ | High | None | Plugin testing |
| tree-sitter | Code parser | optional dep | extraction/ | Medium | Memory (AST) | Code entity extraction |
| SQLite | Database | stdlib | graph/ | High | File I/O (knowledge.db) | Knowledge graph storage |
| NetworkX | Graph lib | dep | graph/ | High | Memory | Graph traversal |

## MoAI-ADK Skills

| Skill | Trigger | Use Case |
|---|---|---|
| moai:run | /moai run | SPEC implementation via TDD/DDD |
| moai:plan | /moai plan | SPEC document creation |
| moai:sync | /moai sync | Documentation sync and PR |
| moai:fix | /moai fix | Auto-fix lint/type errors |
| moai:loop | /moai loop | Iterative fix until done |
| moai:review | /moai review | Code review with security |

## Production Gaps Identified (2026-04-28)

| Gap | Priority | Effort | Impact |
|---|---|---|---|
| Any types in tree-sitter extractors | Medium | Medium | Type safety |
| Logging only in pipeline.py | Medium | Low | Observability |
| CLI coverage 16-21% | Low | Low | Test completeness |
| ML model cleanup in semantic extractor | Low | Low | Memory management |
| No async I/O | Low | High | Performance (future) |

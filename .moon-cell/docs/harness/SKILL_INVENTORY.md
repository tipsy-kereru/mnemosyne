# Skill and Tool Inventory

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-29 09:50:42 NZST

## Project Tools

| Capability | Type | Location | Scope | Trust Level | Side Effects | Recommended Use |
|---|---|---|---|---|---|---|
| ruff | CLI linter | `pyproject.toml` | `mnemosyne/`, `tests/` | High | File modification only with `--fix` | Lint and formatting gate |
| mypy | Type checker | dev environment | `mnemosyne/` | High | None | Type safety gate |
| pytest | Test runner | `pyproject.toml` | `tests/` | High | Test DB/temp files | Regression and acceptance verification |
| pytest-cov | Coverage tool | optional dev dependency | `mnemosyne/`, `tests/` | High | Coverage artifacts | Coverage warning threshold |
| jest | JS test runner | `joplin-plugin/knowledge-graph/package.json` | Joplin plugin | High | Node cache/output | Plugin verification |
| tree-sitter | Code parser | optional dependency groups | extraction modules | Medium | In-memory AST parsing | Deterministic code extraction |
| SQLite | Database | stdlib / local files | graph storage | High | Local DB file I/O | Knowledge graph persistence |
| NetworkX | Graph library | project dependency | graph traversal | High | Memory | Path and relation traversal |

## MCP Servers Declared in `.mcp.json`

| Server | Purpose | Command Source | Trust / Notes |
|---|---|---|---|
| context7 | Up-to-date documentation and code examples | `npx -y @upstash/context7-mcp@latest` | Network/package execution; use only when docs lookup is needed |
| sequential-thinking | Step-by-step reasoning for complex problems | `npx -y @modelcontextprotocol/server-sequential-thinking` | Network/package execution; use only when complexity warrants it |
| moai-lsp | LSP code intelligence | `moai mcp lsp` | Local command; useful for definitions/references/diagnostics if available |

## MoAI-ADK Skills / Commands

| Skill | Trigger | Use Case |
|---|---|---|
| moai:run | `/moai run` | SPEC implementation via TDD/DDD |
| moai:plan | `/moai plan` | SPEC document creation |
| moai:sync | `/moai sync` | Documentation sync and PR preparation |
| moai:fix | `/moai fix` | Auto-fix lint/type errors |
| moai:loop | `/moai loop` | Iterative fix until done |
| moai:review | `/moai review` | Code review with security review |

## Moon Cell / Codex-Oriented Capabilities

| Capability | Source | Recommended Use |
|---|---|---|
| moon-cell | Local skill | Harness init/update/status and bridge design |
| analyze | OMX skill | Read-only repository analysis before changes |
| code-review | OMX skill | Comprehensive code review when requested or high-risk |
| security-review | OMX skill | Security-sensitive changes or MCP trust review |
| ralph / ralplan / team | OMX runtime workflows | Use only when OMX runtime surface is available and task warrants it |
| Codex native subagents | Current Codex session | Independent bounded subtasks when parallelism materially helps |

## Current Quality / Production Status

| Metric | Current Evidence | Source |
|---|---|---|
| Tests | 413 passed, 2 skipped | `python3 -m pytest --tb=short -q` on 2026-04-29 |
| Type safety | mypy 0 errors | README quality summary |
| Lint | ruff 0 violations | README quality summary |
| Coverage | 81%+ | README quality summary |
| SPECs | 8 completed, 0 in progress | README quality summary |

## Known Gaps / Candidates

| Gap | Priority | Effort | Impact | Recommended Routing |
|---|---|---|---|---|
| `datetime.utcnow()` deprecation warnings | Medium | Low/Medium | Future Python compatibility | SPEC or targeted cleanup with tests |
| Async I/O | Low | High | Performance / concurrency | Separate architecture SPEC |
| Root AGENTS.md Moon Cell bridge | Low | Low | Better Codex portability | Requires explicit G-BRIDGE confirmation |

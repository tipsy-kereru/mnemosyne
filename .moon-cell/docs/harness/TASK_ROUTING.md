# Task Routing

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-28 19:07:08 NZST

## SPEC-PROD-001: Production Hardening

| Task ID | Task Type | Owner Role | Reviewer Role | Pattern Provider | Files | Model Class | Parallel Group |
|---|---|---|---|---|---|---|---|
| TASK-A | Logging | Agent-A (Logger) | MoAI Gate | MoAI-ADK | knowledge_graph.py, scope_manager.py, code_parser.py | implementation | P1 |
| TASK-B | Type safety | Agent-B (Typer) | MoAI Gate | MoAI-ADK | languages/*.py (4 files) | implementation | P1 |
| TASK-C | CLI tests | Agent-C (Tester) | MoAI Gate | MoAI-ADK | tests/test_cli.py | implementation | P1 |
| TASK-D | ML cleanup | Agent-D (Fixer) | MoAI Gate | MoAI-ADK | slm_extractor.py | implementation | P1 |

All 4 tasks in P1 group have zero file overlap — safe for parallel execution.

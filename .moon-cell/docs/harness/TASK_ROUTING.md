# Task Routing

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-28 19:49:39 NZST

## SPEC-PROD-001: Production Hardening (COMPLETED)

| Task ID | Task Type | Status | Files |
|---|---|---|---|
| TASK-A | Logging | completed | knowledge_graph.py, scope_manager.py, code_parser.py |
| TASK-B | Type safety | completed | languages/*.py (4 files) |
| TASK-C | CLI tests | completed | tests/test_cli.py |
| TASK-D | ML cleanup | completed | slm_extractor.py |

## SPEC-PROD-002: Remaining Production Polish (DRAFT)

| Task ID | Task Type | Owner Role | Files | Model Class | Parallel Group |
|---|---|---|---|---|---|
| TASK-E | Extraction CLI tests | Tester | tests/test_extraction_cli.py | implementation | P2 |
| TASK-F | Semantic coverage | Tester | tests/test_semantic_coverage.py | implementation | P2 |
| TASK-G | Fallback coverage | Tester | tests/test_fallback_coverage.py | implementation | P2 |
| TASK-H | Protocol + entry tests | Tester | tests/test_language_protocol.py, tests/test_main_entry.py | implementation | P2 |
| TASK-I | CLI output modernize | Implementer | extraction/cli.py, pipeline.py | implementation | P2 |
| TASK-J | Language edge cases | Tester | tests/test_language_edge_cases.py | implementation | P2 |

P2 tasks E/F/G/H/J test-only (no source overlap). TASK-I touches source files (cli.py, pipeline.py).
Recommended: execute E/F/G/H/J in parallel, then I sequentially.

## FUTURE-001: Async I/O (BLOCKER)

Blocked on: API design decision for async migration. 37 cursor + 4 connection operations.
Requires separate SPEC when async decision is made.

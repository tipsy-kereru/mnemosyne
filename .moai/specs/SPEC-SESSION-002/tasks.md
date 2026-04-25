## Task Decomposition
SPEC: SPEC-SESSION-002

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T-001 | CodeEntity dataclass scope_id/source_channel + extract_file() parameter extension | REQ-005, REQ-006 | - | core/extraction/deterministic/code_parser.py, tests/test_integration_session.py | pending |
| T-002 | ExtractedEntity/Relation dataclass scope fields + SLM extractor parameter extension | REQ-005, REQ-006 | - | core/extraction/semantic/slm_extractor.py, tests/test_integration_session.py | pending |
| T-003 | Python regression verification (75 existing tests) | REQ-006 | T-001, T-002 | tests/test_knowledge_graph_session.py, tests/test_scope_manager.py | pending |
| T-004 | Joplin frontmatter parsing + scope-aware entity extraction + Jest infra setup | REQ-001, REQ-002 | - | joplin-plugin/knowledge-graph/src/index.ts, joplin-plugin/knowledge-graph/src/__tests__/*.test.ts | pending |
| T-005 | Joplin scope-aware wiki links with @modifiers | REQ-003 | T-004 | joplin-plugin/knowledge-graph/src/index.ts | pending |
| T-006 | Joplin scope persistence (save/load scopes) | REQ-004 | T-004 | joplin-plugin/knowledge-graph/src/index.ts | pending |
| T-007 | Documentation updates (AGENTS.md + CLAUDE.md) | REQ-007 | T-001, T-002, T-004 | AGENTS.md, CLAUDE.md | pending |
| T-008 | Integration test completion | All | T-001 thru T-006 | tests/test_integration_session.py | pending |

# Task Routing

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-05-31 03:14:25 NZST

## Completed SPECs

| SPEC ID | Task Type | Status | Owner Role | Reviewer Role | Verification / Evidence |
|---|---|---|---|---|---|
| SPEC-SESSION-001 | Scope/session model | completed | Implementer | Reviewer | `.moai/specs/SPEC-SESSION-001/spec.md` |
| SPEC-SESSION-002 | Session integration | completed | Implementer | Reviewer | `.moai/specs/SPEC-SESSION-002/spec.md` |
| SPEC-PKG-001 | Packaging/distribution | completed | Implementer | Reviewer | `.moai/specs/SPEC-PKG-001/spec.md` |
| SPEC-TS-001 | Tree-sitter extraction | completed | Implementer | Test Architect | `.moai/specs/SPEC-TS-001/spec.md` |
| SPEC-PIPE-001 | Extraction pipeline | completed | Implementer | Test Architect | `.moai/specs/SPEC-PIPE-001/spec.md` |
| SPEC-QUALITY-001 | Code quality 10/10 | completed | Test Architect | Reviewer | `.moai/specs/SPEC-QUALITY-001/spec.md` |
| SPEC-PROD-001 | Production hardening | completed | Implementer | Reviewer | `.moai/specs/SPEC-PROD-001/spec.md` |
| SPEC-PROD-002 | Remaining production polish | completed | Implementer / Test Architect | Reviewer | `.moai/specs/SPEC-PROD-002/spec.md` |
| SPEC-RENAME-001 | Project name canonicalization | completed | Implementer | Reviewer | `.moai/specs/SPEC-RENAME-001/spec.md` |
| SPEC-INGEST-001 | Knowledge graph ingestion pipeline | completed | Implementer | Test Architect | `.moai/specs/SPEC-INGEST-001/spec.md`; 25 new tests, 440 total pass |
| SPEC-WARN-001 | Pytest warning remediation | completed | Implementer | Test Architect | `.moon-cell/specs/SPEC-WARN-001.md`; 441 passed, 0 warnings |
| SPEC-WIKI-001 | LLM Wiki hardening and graph synchronization | completed | Implementer | Test Architect / Security Reviewer | `.moon-cell/specs/SPEC-WIKI-001.md`; 450 passed; ruff clean; mypy clean; CLI smoke passed; QG-006 passed |
| SPEC-WIKI-002 | Joplin/editor UX polish | completed | Implementer / UX Writer | QA / Test Architect | `.moon-cell/specs/SPEC-WIKI-002.md`; 45 focused tests; 452 full tests; ruff clean; mypy clean; CLI smoke passed |
| SPEC-WIKI-004 | Multi-process wiki writer locking | completed | Implementer | Reliability Reviewer / Test Architect | `.moon-cell/specs/SPEC-WIKI-004.md`; 39 focused tests; 456 full tests; ruff clean; mypy clean; CLI smoke passed |
| SPEC-WIKI-003 | Conflict-metadata contradiction summaries | completed | Implementer / Solution Architect | Security Reviewer / Test Architect | `.moon-cell/specs/SPEC-WIKI-003.md`; 79 focused tests; 459 full tests; ruff clean; mypy clean; CLI smoke passed |
| SPEC-WIKI-005 | Conflict resolution review UX | completed | Implementer / CLI Designer | Security Reviewer / Test Architect | `.moon-cell/specs/SPEC-WIKI-005.md`; 81 focused tests; 461 full tests; ruff clean; mypy clean; CLI smoke passed |
| SPEC-WIKI-007 | Wiki prune/stale/tombstone reconciliation | completed | Implementer / Data Lifecycle Architect | Safety Reviewer / Test Architect | `.moon-cell/specs/SPEC-WIKI-007.md`; 83 focused tests; 463 full tests; ruff clean; mypy clean; CLI smoke passed |
| SPEC-WIKI-006 | Optional semantic contradiction discovery | completed | Implementer / AI Safety Reviewer | Security Reviewer / Test Architect | `.moon-cell/specs/SPEC-WIKI-006.md`; 85 focused tests; 465 full tests; ruff clean; mypy clean; CLI smoke passed |
| SPEC-HARNESS-001 | Root bridge and Moon Cell tracking policy | completed | Harness Engineer | Repository Maintainer | `.gitignore` `!.moon-cell/` exception; `AGENTS.md` Moon Cell pointer added; approved 2026-05-04 |
| SPEC-ARCH-ASYNC-001 | Async I/O architecture design | completed | Solution Architect / Implementer | Test Architect | `.moon-cell/specs/SPEC-ARCH-ASYNC-001.md`; T1-T4 complete 2026-05-05; async fetch/extract implemented |
| SPEC-PROJECT-REGISTRY-001 | Project-scoped knowledge graph with hash-based registry | completed | Implementer | Test Architect | `.moon-cell/specs/SPEC-PROJECT-REGISTRY-001.md`; projects table + auto-detection + CLI implemented 2026-05-07 |
| SPEC-PERF-001 | Performance tuning & Hybrid core | completed | Performance Architect | Test Architect | `.moon-cell/specs/SPEC-PERF-001.md`; SQLite WAL & synchronous, environment lock dir, Rust core fallback implemented 2026-06-01 |

## Active / Planned SPECs

No active or planned SPECs. All SPECs completed or in candidate status.

| SPEC ID | Task Type | Status | Owner Role | Reviewer Role | Verification / Evidence |
|---|---|---|---|---|---|
| (none) | — | — | — | — | — |

## Candidate SPECs

| SPEC ID | Task Type | Status | Owner Role | Reviewer Role | Promotion Trigger |
|---|---|---|---|---|---|
| SPEC-WIKI-008 | Large vault incremental index optimization | candidate | Performance Architect | Test Architect | Large-vault benchmarks exceed agreed thresholds |
| SPEC-JOPLIN-001 | External Tool Integration API | completed | Solution Architect / Backend Developer | API Reviewer / Test Architect | 15 endpoints, 19 tests, merged to main 2026-05-31 |
| SPEC-JOPLIN-002 | Joplin Plugin HTTP Bridge | candidate | Frontend Developer | Integration Reviewer | SPEC-JOPLIN-001 completed |
| SPEC-JOPLIN-003 | Real-Time Graph Visualization | completed | Frontend Developer | UX Reviewer | SPEC-JOPLIN-002 completed |
| SPEC-JOPLIN-004 | Edit-to-Graph Real-Time Sync | completed | Frontend Developer | Test Architect | SPEC-JOPLIN-002/003 completed |

## Recommended Execution Order

| Order | SPEC | Reason |
|---|---|---|
| 1 | SPEC-JOPLIN-001 | Foundation: HTTP API required by all downstream Joplin SPECs |
| 2 | SPEC-JOPLIN-002 | Bridge: connects plugin to mnemosyne DB via API |
| 3 | SPEC-JOPLIN-003 | Visualization: graph view, backlinks, autocomplete |
| 4 | SPEC-JOPLIN-004 | Real-time sync: edit-to-graph pipeline |
| 5 | SPEC-PERF-001 | Completed 2026-06-01; SQLite WAL & lock paths and Rust core fallback |
| 6 | SPEC-WIKI-008 | Only after large-vault benchmark evidence |
| 7 | SPEC-HARNESS-001 | Harness policy cleanup is optional and not product-critical |

## Harness Refresh 2026-04-29

| Task ID | Task Type | Owner Role | Reviewer Role | Pattern Provider | Capability Source | Runtime Form | Model Class | Inputs | Outputs | Verification |
|---|---|---|---|---|---|---|---|---|---|---|
| HARNESS-REFRESH-001 | Harness metadata update | Handoff Writer | Reviewer | ECC-like | moon-cell skill | Main agent | cheap-fast | `.moon-cell/**`, README, pyproject, SPEC list | Updated `.moon-cell` docs | Manifest/changelog/handoff updated |
| HARNESS-BRIDGE-001 | Codex bridge creation | Capability Router | Reviewer | ECC-like | Current Codex session metadata | Main agent | implementation | Model routing docs, current runtime metadata | `.moon-cell/bridges/codex/MODEL_MAP.md` | Root bridge files untouched |

## Backlog / Deferred Work

| Task ID | Task Type | Status | Owner Role | Notes | Gate |
|---|---|---|---|---|---|
| FUTURE-001 | Async I/O | completed | Solution Architect / Implementer | SPEC-ARCH-ASYNC-001 completed 2026-05-05; async methods implemented | Completed |
| FUTURE-002 | Timezone-aware datetime migration | resolved for warning cleanup | Spec Architect / Implementer | SPEC-WARN-001 removed deprecated timestamp warnings while preserving naive UTC string shape | Completed |
| FUTURE-003 | Optional root AGENTS.md Moon Cell bridge | candidate SPEC drafted | Capability Router | Candidate SPEC-HARNESS-001; root/ignore changes still require explicit approval | G-BRIDGE |
| FUTURE-004 | LLM Wiki editor integration polish | completed by SPEC-WIKI-002 | UX Writer / QA | Joplin/Obsidian-style editor workflow and smoke fixture | Completed |
| FUTURE-005 | LLM Wiki contradiction summaries | completed by SPEC-WIKI-003 | Solution Architect / Security Reviewer | Deterministic summaries from conflict metadata | Completed |
| FUTURE-006 | Concurrent wiki writer locking | completed by SPEC-WIKI-004 | Solution Architect / Test Architect | Stdlib write-lock context and timeout behavior | Completed |
| FUTURE-007 | Conflict resolution UX | completed by SPEC-WIKI-005 | Product Architect / CLI Designer | Review metadata mutation without deleting evidence | Completed |
| FUTURE-008 | Semantic contradiction discovery | completed by SPEC-WIKI-006 | Solution Architect / AI Safety Reviewer | Opt-in local semantic review candidates; remote models disabled | Completed |
| FUTURE-009 | Wiki prune/stale/tombstone lifecycle | completed by SPEC-WIKI-007 | Data Lifecycle Architect | Non-destructive stale planning and tombstone records | Completed |
| FUTURE-010 | Large vault index optimization | candidate SPEC drafted | Performance Architect | Candidate SPEC-WIKI-008; benchmark-gated | Performance Gate |
| FUTURE-011 | External tool integration API | candidate SPEC created | Solution Architect / Backend Developer | Candidate SPEC-JOPLIN-001; localhost HTTP API | User selects |
| FUTURE-012 | Joplin plugin HTTP bridge | candidate SPEC created | Frontend Developer | Candidate SPEC-JOPLIN-002; depends on FUTURE-011 | FUTURE-011 completed |
| FUTURE-013 | Real-time graph visualization | candidate SPEC created | Frontend Developer | Candidate SPEC-JOPLIN-003; D3.js graph, backlinks | FUTURE-012 completed |
| FUTURE-014 | Edit-to-graph real-time sync | candidate SPEC created | Frontend Developer | Candidate SPEC-JOPLIN-004; onContentChange pipeline | FUTURE-012/013 completed |

## Routing Rules

| Request Shape | First Role | Next Role | Required Evidence |
|---|---|---|---|
| Bugfix or regression | Test Architect | Implementer, Reviewer | Reproducing test or regression command |
| New feature | Spec Architect | Solution Architect, Implementer | SPEC or documented acceptance criteria |
| Refactor / cleanup | Solution Architect | Test Architect, Implementer | Existing behavior locked by tests |
| Harness update | Capability Router | Handoff Writer, Reviewer | Manifest/changelog/handoff updates |
| Release | Release Agent | Reviewer | QG-002 evidence and changelog |
| LLM Wiki / graph sync change | Test Architect | Implementer, Security Reviewer | QG-006 evidence: focused wiki tests, full tests, ruff, mypy, CLI smoke |
| Editor UX docs | UX Writer | QA | Folder fixture and no-token editor guidance |
| Contradiction summaries | Solution Architect | Security Reviewer / Test Architect | Conflict adapter tests, redaction tests, cautious language review |
| Semantic contradiction discovery | Solution Architect / AI Safety Reviewer | Security Reviewer / Test Architect | Opt-in command, local/offline disclosure, uncertainty wording, redacted evidence, false-positive fixtures |
| Concurrent writer locking | Solution Architect | Reliability Reviewer / Test Architect | Held-lock tests, timeout behavior, non-corruption evidence |
| mnemosyne serve API | Solution Architect / Backend Developer | API Reviewer / Test Architect | HTTP endpoint tests, response time benchmarks, regression check |
| Joplin plugin bridge | Frontend Developer | Integration Reviewer | API client unit tests, graceful degradation tests |
| Graph visualization | Frontend Developer | UX Reviewer | Graph renders correctly, node interaction works, backlinks accurate |
| Real-time sync pipeline | Frontend Developer | Test Architect | Debounce timing, entity diffing, graph update animation |

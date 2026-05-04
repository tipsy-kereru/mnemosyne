# Changelog

All notable changes to the Mnemosyne Knowledge Graph project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.8] - 2026-05-03

### Added
- Added opt-in local semantic contradiction discovery for SPEC-WIKI-006.
- Added `mnemosyne wiki semantic-contradictions` with explicit local-offline processing metadata and no remote model calls.
- Added distinct persisted review schema `mnemosyne.semantic_contradiction_candidates.v1` under `review/semantic-contradictions.*`.
- Added bounded redacted evidence excerpts, confidence, rationale, uncertainty wording, generated-at metadata, and separate semantic status/lint warnings.

### Changed
- README and Korean manual now document the semantic discovery safety boundary: candidates are review items only, deterministic conflicts remain separate, and graph facts are never merged/deleted by discovery.

### Quality Metrics
- focused wiki/ingest/CLI tests: 85 passed
- pytest: 465 passed
- ruff: 0 violations
- mypy: 0 errors across 37 source files

## [0.3.7] - 2026-05-03

### Added
- Added non-destructive stale wiki/graph reconciliation planning for SPEC-WIKI-007.
- Added `mnemosyne wiki prune` dry-run plans with candidate IDs, reasons, risk labels, paths/entities/sources, and manual-note previews.
- Added `mnemosyne wiki prune --apply-tombstones` to write Markdown tombstone records without deleting wiki pages or graph facts.
- Added stale candidate counts to `mnemosyne wiki status` and stale warnings to `mnemosyne wiki lint`.

### Changed
- README and Korean manual now document stale planning, tombstone records, and the zero-delete cleanup contract.

### Quality Metrics
- focused wiki/ingest/CLI tests: 83 passed
- pytest: 463 passed
- ruff: 0 violations
- mypy: 0 errors across 37 source files
- CLI smoke: `mnemosyne wiki rebuild|prune --format json|prune --apply-tombstones` passed against temp DB/wiki roots

## [0.3.6] - 2026-05-03

### Added
- Added conflict review CLI workflow for SPEC-WIKI-005.
- Added `mnemosyne wiki contradictions` to list graph-backed review items with stable `conflict_id` values.
- Added `mnemosyne wiki resolve <conflict_id>` to update resolution metadata with optional note/reviewer and `--dry-run`.
- Added graph history-backed audit coverage for conflict resolution metadata changes.

### Changed
- Wiki contradiction sections now include the stable conflict ID that can be used by the review CLI.
- Status/lint continue to separate unresolved from resolved/ambiguous conflicts through resolution counts and unresolved-only lint warnings.
- README and Korean manual now document conflict listing and resolution review commands.

### Quality Metrics
- focused wiki/ingest/CLI tests: 81 passed
- pytest: 461 passed
- ruff: 0 violations
- mypy: 0 errors across 37 source files

## [0.3.5] - 2026-05-03

### Added
- Added deterministic conflict-metadata contradiction summaries for LLM Wiki entity pages (SPEC-WIKI-003).
- Added `WikiContradiction` normalization for legacy `seen_at` conflict records, current `detected_at` records, missing source attribution, and resolution statuses.
- Added contradiction counts to `mnemosyne wiki status --format json` when a graph DB is available.
- Added `mnemosyne wiki lint` warnings for unresolved contradictions; `--strict` now fails on those warnings.
- Added ingest conflict metadata fields: `source_id`, `detected_at`, and `resolution`.

### Changed
- Entity property rendering no longer dumps raw `conflicts` dictionaries; unresolved conflicts render as cautious `Potential contradictions` / `Needs review` review items.
- Conflict values are redacted with the same policy used for wiki source excerpts.
- README and Korean manual document deterministic contradiction review semantics and resolution statuses.

### Quality Metrics
- focused wiki/ingest/CLI tests: 79 passed
- pytest: 459 passed
- ruff: 0 violations
- mypy: 0 errors across 37 source files
- CLI smoke: `mnemosyne wiki rebuild|status|lint --format json` passed against temp DB/wiki roots, including unresolved contradiction and strict-lint failure behavior

## [0.3.4] - 2026-05-03

### Added
- Added stdlib single-writer locking for generated LLM Wiki writes (SPEC-WIKI-004).
- Added `.mnemosyne-wiki.lock` metadata with owner token, PID, hostname, action, creation time, and wiki root.
- Added lock timeout JSON/text error reporting for `mnemosyne wiki rebuild`.
- Added regression tests for held locks, stale-lock diagnostics, foreign-lock cleanup safety, and non-corruption on rebuild lock contention.

### Changed
- Documented wiki writer locking, default timeout, read-only command behavior, and stale-lock recovery guidance in README and Korean manual.

### Quality Metrics
- focused wiki/ingest tests: 39 passed
- pytest: 456 passed
- ruff: 0 violations
- mypy: 0 errors across 37 source files
- CLI smoke: `mnemosyne wiki rebuild|status|lint --format json --lock-timeout 1` passed against temp DB/wiki roots

## [0.3.3] - 2026-05-02

### Added
- Polished the LLM Wiki editor workflow (SPEC-WIKI-002) for Joplin/Obsidian-style Markdown folders.
- Added generated-page editing guidance that explains rebuildable sections and safe manual note zones.
- Added editor-neutral wiki folder smoke coverage for index, log, source, and entity pages.
- Added CLI help copy that points users to explicit `--wiki-root` editor workflows without requiring Joplin tokens.

### Changed
- README and Korean manual now document safe Joplin/Obsidian folder usage, token-free import guidance, and `MNEMOSYNE:GENERATED` edit boundaries.

### Quality Metrics
- focused wiki/CLI tests: 45 passed
- pytest: 452 passed
- ruff: 0 violations
- mypy: 0 errors across 37 source files
- CLI smoke: `mnemosyne wiki rebuild|status|lint --format json` passed against temp DB/wiki roots

## [0.3.2] - 2026-05-02

### Added
- Hardened the LLM Wiki layer (SPEC-WIKI-001) with `mnemosyne wiki status`, `lint`, `rebuild`, and `doctor` commands.
- Added compact YAML frontmatter for generated source/entity/index/log pages.
- Added safe source excerpt controls: excerpts are omitted by default and `--wiki-excerpts` opts into bounded redacted excerpts.
- Added wiki rebuild from graph rows while preserving manual notes outside generated markers.
- Added entity/relation merge semantics for ingest updates, including conflict metadata and entity history events.

### Changed
- Documented the LLM Wiki + knowledge graph workflow in README and Korean manual.
- Added QG-006 Moon Cell gate for wiki/graph consistency changes.

### Quality Metrics
- pytest: 450 passed
- ruff: 0 violations
- mypy: 0 errors across 37 source files
- CLI smoke: `mnemosyne wiki rebuild|status|lint --format json` passed against temp DB/wiki roots

## [0.3.1] - 2026-04-30

### Fixed
- Eliminated pytest warning noise from project-owned UTC timestamp creation (SPEC-WARN-001)
- Centralized UTC metadata timestamp creation in `mnemosyne.timestamps.utc_now_iso()`
- Preserved existing naive UTC ISO string shape while avoiding deprecated naive UTC clock APIs

### Added
- Timestamp helper regression test to lock current storage/output timestamp shape

### Quality Metrics
- pytest: 441 passed, 0 warnings
- ruff: 0 violations
- mypy: 0 errors

## [0.3.0] - 2026-04-28

### Added
- Structured logging across core modules (knowledge_graph, scope_manager, code_parser)
- CLI test coverage raised from 16-21% to 95-97% (SPEC-PROD-001 REQ-003)
- ML model cleanup methods and context managers on GLiNER2Extractor, REBELExtractor, SemanticExtractor
- 90 new tests for remaining production polish (SPEC-PROD-002)
  - Extraction CLI tests: path validation, domain routing, output formats
  - Semantic SLM extractor tests: GLiNER, REBEL, cleanup, context managers, fallback paths
  - Code parser regex fallback tests: Python, JS, Go, Rust
  - LanguageExtractor protocol conformance tests
  - `__main__.py` entry point tests
  - Language edge case tests: async, JSX, traits, generics

### Changed
- Replaced 41 `Any` types with proper `Tree`/`Node`/`Language` annotations in language extractors
- Added 26 `node.text` None guards across 4 language extractors for mypy compliance
- CLI `print()` calls now use explicit `sys.stdout`/`sys.stderr` separation
- Total test count: 323 → 413 (SPEC-PROD-001) → 413 (SPEC-PROD-002)

### Quality Metrics
- pytest: 413 passed, 2 skipped
- mypy: 0 errors (27+ source files)
- ruff: 0 violations
- Overall coverage: 81%+

## [0.2.2] - 2026-04-28

### Changed
- Updated SPEC document statuses to reflect implementation completion
  - SPEC-SESSION-001: draft → completed (hierarchical scope system)
  - SPEC-SESSION-002: draft → completed (session integration layer)
  - SPEC-PKG-001: draft → completed (Python package structure)
  - SPEC-TS-001: draft → completed (tree-sitter AST extraction)
  - SPEC-PIPE-001: draft → completed (extraction pipeline orchestration)

## [0.2.1] - 2026-04-27

### Fixed
- Resolved 12 mypy type errors across 4 files (SPEC-QUALITY-001)
  - Added None guards for optional model fields in slm_extractor.py
  - Added None guards for tree-sitter node.text in python_extractor.py
  - Added TYPE_CHECKING import for ParseResult in code_parser.py
  - Fixed Optional[str] type annotation in knowledge_graph.py
- Resolved 61 ruff lint errors across mnemosyne/ and tests/ (SPEC-QUALITY-001)
  - Removed 35 unused imports (auto-fixed via ruff --fix)
  - Fixed 7 unused variables in test files
  - Fixed duplicate .ts key to .tsx in SUPPORTED_LANGUAGES
  - Converted 3 f-strings without placeholders to regular strings
- Achieved zero-error quality gate: mypy 0, ruff 0, pytest 295/2, jest 21/21

## [0.2.0] - 2026-04-26

### Added
- Tree-sitter AST parsing integration (SPEC-TS-001) with 6-language support
  - Language-specific extractors: Python, JavaScript, TypeScript, TSX, Go, Rust
  - Protocol-based architecture using `LanguageExtractor` protocol
  - Import graph and call graph extraction
  - 96 new tests (223 total coverage)
- End-to-end extraction pipeline (SPEC-PIPE-001) with 3-layer architecture
  - Deterministic layer: Tree-sitter AST parsing (zero LLM)
  - Semantic layer: GLiNER2 NER and REBEL relation extraction (local SLM)
  - Synthesis layer: Optional LLM-based complex query processing
  - Multi-domain routing: coding, daily, legal
  - Incremental extraction with SHA-256 content hash tracking
  - KnowledgeGraph storage with entity deduplication
  - Extraction reports: summary, JSON, wiki formats
  - Error resilience with per-file isolation
  - 70 new tests (295 total coverage)

### Changed
- Updated extraction documentation to reflect tree-sitter implementation (no longer "planned")
- Updated CLI examples to include new pipeline commands

### Removed
- Deprecated regex-based code parser (replaced by tree-sitter AST parsing)

## [0.1.0] - 2026-04-26

### Added
- PEP 621 compliant `pyproject.toml` with dependency groups (core, deterministic, semantic, dev, all)
- Python package structure: `mnemosyne/` with `__init__.py` files and public API exports
- CLI entry points: `mnemosyne`, `mnemosyne-query`, `mnemosyne-extract`
- Version management via `importlib.metadata` with fallback
- Package import tests (`tests/test_package.py`)
- CLI entry point tests (`tests/test_cli.py`)
- Session-scoped knowledge graph with hierarchical scopes (project → topic → session)
- Deterministic extraction (regex-based, tree-sitter planned)
- Semantic extraction (GLiNER2/REBEL with fallback)
- Joplin plugin for Obsidian-like wiki-link experience

### Changed
- Renamed `core/` directory to `mnemosyne/` for proper Python packaging
- Updated all import paths from `core.*` to `mnemosyne.*`
- Deprecated `requirements.txt` in favor of `pyproject.toml`

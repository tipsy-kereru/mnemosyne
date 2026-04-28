# Changelog

All notable changes to the Mnemosyne Knowledge Graph project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

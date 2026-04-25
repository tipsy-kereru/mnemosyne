# Changelog

All notable changes to the Mnemosyne Knowledge Graph project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

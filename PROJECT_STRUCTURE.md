# Mnemosyne Project Structure Improvement Plan

## Version
- **Document Version**: 1.0.0
- **Created**: 2025-06-28
- **Status**: Design Phase

## Current Structure Analysis

### Directory Tree (Current)

```
mnemosyne/
├── mnemosyne/              # Main Python package
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py              # Entry point
│   ├── extensions/         # Extensible payloads
│   ├── extraction/         # Extraction pipelines
│   ├── graph/              # Knowledge graph engine
│   ├── hooks/              # Hook scripts
│   ├── ingest/             # Ingestion pipeline
│   ├── mcp/                # MCP server
│   ├── query/              # Query engine
│   ├── raw/                # Raw source storage
│   ├── schema/             # Domain schemas
│   ├── serve/              # Server module
│   ├── skills/             # Agent skills
│   └── wiki/               # LLM Wiki maintainer
├── mnemosyne-core/         # Rust accelerator (107 lines)
│   ├── Cargo.toml
│   └── src/lib.rs
├── joplin-plugin/          # TypeScript plugin
├── tests/                  # 860+ tests
├── docs/                   # Documentation
└── [config files]
```

### Issues Identified

| Issue | Severity | Impact |
|-------|----------|--------|
| Flat structure with deep nesting | Medium | Hard to navigate |
| Mixed concerns (CLI in root) | Medium | Confusion |
| Inconsistent naming (some `.py`, some directories) | Low | Minor confusion |
| No clear layer separation | High | Maintenance burden |
| Rust core is hidden in subdirectory | Medium | Underutilized |

---

## Proposed Improved Structure

### Phase 1: Reorganization (No Code Changes)

```
mnemosyne/
├── README.md
├── CHANGELOG.md
├── MANUAL.md
├── ARCHITECTURE.md          # NEW: System architecture
├── CONTRIBUTING.md           # NEW: Development guide
├── pyproject.toml
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── release.yml
│
├── core/                     # RENAMED: mnemosyne → core
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   └── main.py           # Moved from cli.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py       # Configuration management
│   │
│   ├── domain/               # NEW: Domain models
│   │   ├── __init__.py
│   │   ├── entities.py       # Entity types
│   │   ├── relations.py      # Relation types
│   │   └── schemas.py        # Domain schemas (moved from schema/)
│   │
│   ├── graph/                # Knowledge graph
│   │   ├── __init__.py
│   │   ├── db.py             # Database (SQLite)
│   │   ├── graph.py          # Graph operations
│   │   ├── query.py          # Query engine
│   │   └── scope.py          # Scope management
│   │
│   ├── wiki/                 # LLM Wiki
│   │   ├── __init__.py
│   │   ├── builder.py        # Wiki generation
│   │   ├── linker.py         # Link resolution
│   │   ├── lint.py           # Wiki linting
│   │   └── lock.py           # Write locking
│   │
│   ├── ingest/               # Ingestion pipeline
│   │   ├── __init__.py
│   │   ├── file.py           # File ingestion
│   │   ├── url.py            # URL fetching
│   │   ├── hash.py           # Content hashing
│   │   └── fts.py            # Full-text search
│   │
│   ├── extraction/           # Extraction
│   │   ├── __init__.py
│   │   ├── deterministic/    # Zero-LLM extraction
│   │   ├── semantic/         # ML-based extraction
│   │   └── synthesis/        # LLM synthesis
│   │
│   ├── query/                # Query engine
│   │   ├── __init__.py
│   │   ├── natural.py        # Natural language query
│   │   └── structured.py     # Structured query
│   │
│   ├── serve/                # Server
│   │   ├── __init__.py
│   │   └── mcp.py            # MCP server
│   │
│   └── extensions/           # Extensible payloads
│       ├── __init__.py
│       └── schemas/          # Extension schemas
│
├── rust-core/                # RENAMED: mnemosyne-core → rust-core
│   ├── Cargo.toml
│   ├── src/
│   │   ├── lib.rs
│   │   ├── cli/
│   │   ├── db/
│   │   ├── graph/
│   │   ├── wiki/
│   │   └── ...
│   └── benches/             # NEW: Benchmarks
│
├── ml-agent/                 # NEW: Python ML subagent
│   ├── pyproject.toml
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── semantic/
│   │   ├── llm/
│   │   └── ipc/
│   └── tests/
│
├── plugins/                  # RENAMED: joplin-plugin → plugins
│   └── joplin/
│       ├── package.json
│       └── src/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── docs/
│   ├── api/
│   ├── guides/
│   └── architecture/
│
└── tools/                    # NEW: Development tools
    ├── lint.sh
    ├── test.sh
    └── build.sh
```

### Phase 2: Rust Core Expansion

```
rust-core/
├── Cargo.toml
├── build.rs                  # NEW: Build script
├── src/
│   ├── lib.rs                # PyO3 module entry
│   ├── cli/                  # CLI commands
│   │   ├── mod.rs
│   │   ├── add.rs
│   │   ├── query.rs
│   │   ├── update.rs
│   │   └── wiki.rs
│   ├── db/                   # Database layer
│   │   ├── mod.rs
│   │   ├── conn.rs
│   │   ├── entities.rs
│   │   ├── relations.rs
│   │   └── schema.rs
│   ├── graph/                # Graph operations
│   │   ├── mod.rs
│   │   ├── query.rs
│   │   ├── traversal.rs
│   │   └── metrics.rs
│   ├── wiki/                 # Wiki generation
│   │   ├── mod.rs
│   │   ├── builder.rs
│   │   ├── linker.rs
│   │   ├── frontmatter.rs
│   │   └── rebuild.rs
│   ├── ingest/               # Ingestion
│   │   ├── mod.rs
│   │   ├── file.rs
│   │   └── hash.rs
│   ├── extraction/          # Tree-sitter extraction
│   │   ├── mod.rs
│   │   ├── ast.rs
│   │   └── languages/
│   │       ├── mod.rs
│   │       ├── python.rs
│   │       ├── javascript.rs
│   │       ├── typescript.rs
│   │       ├── go.rs
│   │       └── rust.rs
│   ├── http/                 # HTTP client
│   │   ├── mod.rs
│   │   └── client.rs
│   ├── fts/                  # Full-text search
│   │   ├── mod.rs
│   │   └── search.rs
│   └── bridge/               # IPC to Python ML agent
│       ├── mod.rs
│       └── subagent.rs
├── benches/
│   ├── wiki_rebuild.rs
│   ├── graph_query.rs
│   └── ingest.rs
└── tests/
    ├── integration/
    └── unit/
```

---

## Naming Conventions

### Python Modules

| Convention | Example | Meaning |
|------------|---------|---------|
| `package/` | `core/`, `rust-core/` | Main package directories |
| `module.py` | `query.py` | Single-file modules |
| `package/` | `extraction/` | Multi-file packages |
| `_private.py` | `_utils.py` | Private modules |
| `test_*.py` | `test_wiki.py` | Test modules |

### Rust Modules

| Convention | Example | Meaning |
|------------|---------|---------|
| `module.rs` | `cli.rs` | Single-file modules |
| `module/` | `cli/` | Multi-file modules |
| `mod.rs` | `cli/mod.rs` | Package entry point |
| `tests/` | `cli/tests/` | Module-specific tests |

### CLI Commands

| Convention | Example | Meaning |
|------------|---------|---------|
| `mnemosyne <verb>` | `mnemosyne add` | Main commands |
| `mnemosyne <noun> <verb>` | `mnemosyne wiki status` | Nested commands |

---

## Documentation Standards

### README.md (Root)

```markdown
# Mnemosyne Knowledge Graph

## Quick Links
- [Architecture](ARCHITECTURE.md)
- [Project Structure](PROJECT_STRUCTURE.md)
- [Contributing](CONTRIBUTING.md)
- [Manual](MANUAL.md)

## Quick Start
...
```

### Module README.md

Each major module should have:

```markdown
# Module Name

## Purpose
One-line description.

## Public API
- `function_name()` - Description
- `ClassName` - Description

## Examples
...
```

### Code Documentation

```python
def rebuild_wiki(wiki_root: Path, db_path: Path) -> WikiUpdate:
    """Regenerate wiki pages from graph data.

    Args:
        wiki_root: Root directory of the wiki.
        db_path: Path to the knowledge graph database.

    Returns:
        WikiUpdate with list of modified files.

    Raises:
        WikiLockError: If write lock cannot be acquired.

    Examples:
        >>> rebuild_wiki(Path("~/wiki"), Path("~/kg.db"))
        WikiUpdate(paths=[Path("~/wiki/index.md")])
    """
```

---

## Migration Plan

### Step 1: Documentation (Week 1)
- [ ] Create ARCHITECTURE.md
- [ ] Create PROJECT_STRUCTURE.md
- [ ] Create CONTRIBUTING.md
- [ ] Update README.md

### Step 2: Structure Reorganization (Week 2)
- [ ] Rename `mnemosyne/` → `core/`
- [ ] Rename `mnemosyne-core/` → `rust-core/`
- [ ] Create `ml-agent/` skeleton
- [ ] Rename `joplin-plugin/` → `plugins/joplin/`
- [ ] Update imports across codebase

### Step 3: Module Cleanup (Week 3)
- [ ] Split `cli.py` → `cli/main.py`
- [ ] Move `schema/` → `core/domain/`
- [ ] Create `core/config/`
- [ ] Standardize `__init__.py` exports

### Step 4: Rust Core Expansion (Ongoing)
- [ ] Implement wiki module in Rust
- [ ] Implement graph module in Rust
- [ ] Add benchmarks
- [ ] Add integration tests

---

## Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Module depth (max) | 5 levels | 3 levels | Directory tree analysis |
| Circular dependencies | Unknown | 0 | `pydeps` analysis |
| Documentation coverage | ~30% | 80% | `interrogate` |
| Import time | ~500ms | <300ms | `python -X importtime` |
| Test discovery time | ~5s | <2s | `pytest --collect-only` |

---

## Open Questions

| ID | Question | Status |
|----|----------|--------|
| OQ-1 | Should we use namespace packages? | Open |
| OQ-2 | How to handle deprecation of old import paths? | Open |
| OQ-3 | Should ML agent be a separate repo? | Open |

---

## Appendix: Import Compatibility

### During Migration

```python
# Old import (deprecated)
from mnemosyne.cli import main

# New import
from core.cli.main import main

# Compatibility shim (temporary)
try:
    from core.cli.main import main
except ImportError:
    from mnemosyne.cli import main
```

### After Migration

```python
# Clear, consistent imports
from core.domain.entities import Entity
from core.graph.graph import KnowledgeGraph
from core.wiki.builder import rebuild_wiki
```

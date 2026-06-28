# Mnemosyne Rust Core + Python Subagent Architecture

## Version
- **Document Version**: 1.0.0
- **Created**: 2025-06-28
- **Status**: Design Phase

## Overview

Mnemosyne의 하이브리드 아키텍처: **Rust Core (고성능) + Python Subagent (ML 생태계)**

### Philosophy
- **Rust**: I/O, DB, Graph, Wiki 생성 등 결정론적 고성능 작업
- **Python**: ML/SLM, LLM integration 등 AI/ML 생태계 활용

---

## Current Architecture Analysis

### Existing Mnemosyne Structure

```
mnemosyne/
├── core/
│   ├── graph/          # SQLite + NetworkX
│   ├── wiki/           # Markdown generation
│   ├── ingest/         # File ingestion, URL fetching
│   ├── extraction/     # Multi-layer extraction
│   │   ├── deterministic/  # Tree-sitter (zero-LLM)
│   │   ├── semantic/       # GLiNER2 + Torch (ML)
│   │   └── synthesis/      # Optional LLM
│   ├── mcp/            # MCP server (15+ tools)
│   └── query/          # Natural language query
└── extensions/         # Extensible payloads
```

### Existing Rust Core (`mnemosyne-core/`)

```rust
// Current: 107 lines, 2 functions
fn fast_glob_markdown()      // Directory traversal
fn fast_rebuild_index()      // index.md generation (parallel)
```

**Current Coverage**: ~5% of total codebase

---

## Proposed Architecture

### 1. Layer Separation

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Mnemosyne v2.0                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    RUST CORE (70-80%)                        │  │
│  │  ┌────────────────────────────────────────────────────────┐ │  │
│  │  │  Fast Path: I/O, DB, Graph, Wiki Generation            │ │  │
│  │  │                                                        │ │  │
│  │  │  • CLI (clap)                                         │ │  │
│  │  │  • SQLite (rusqlite)                                  │ │  │
│  │  │  • Graph (petgraph)                                  │ │  │
│  │  │  • Wiki I/O (rayon parallel)                         │ │  │
│  │  │  • HTTP (reqwest)                                    │ │  │
│  │  │  • Tree-sitter (native)                              │ │  │
│  │  │  • FTS (sqlite FTS5 or tantivy)                      │ │  │
│  │  └────────────────────────────────────────────────────────┘ │  │
│  │                                                              │  │
│  │  PyO3 Bridge: Python-callable API                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                      ▲                                                  │
│                      │ IPC/Subprocess                                  │
│                      ↓                                                  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │               PYTHON SUBAGENT (20-30%)                       │  │
│  │  ┌────────────────────────────────────────────────────────┐ │  │
│  │  │  ML/SLM Layer: AI Model Ecosystem                      │ │  │
│  │  │                                                        │ │  │
│  │  │  • GLiNER2 (NER)                                      │ │  │
│  │  │  • Transformers (various models)                      │ │  │
│  │  │  • Torch/Candle (inference)                           │ │  │
│  │  │  • Anthropic/OpenAI API clients                       │ │  │
│  │  │  • SpaCy (NLP fallback)                               │ │  │
│  │  └────────────────────────────────────────────────────────┘ │  │
│  │                                                              │  │
│  │  Entry Point: `mnemosyne-ml-agent`                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2. Module Migration Matrix

| Module | Current | Target | Priority | Complexity |
|--------|---------|--------|----------|------------|
| **CLI** | Python (argparse) | Rust (clap) | P1 | Low |
| **Wiki Generation** | Python + Rust partial | Rust (full) | P1 | Medium |
| **Graph DB** | Python (sqlite3 + NetworkX) | Rust (rusqlite + petgraph) | P1 | Medium |
| **Ingest (core)** | Python | Rust | P1 | Low |
| **FTS** | Python (sqlite FTS5) | Rust (keep FTS5) | P2 | Low |
| **Tree-sitter** | Python binding | Rust native | P2 | Medium |
| **Extraction (deterministic)** | Python | Rust | P2 | High |
| **MCP Server** | Python | Rust (tokio) | P2 | Medium |
| **Query Engine** | Python | Rust | P2 | Medium |
| **Extraction (semantic)** | Python | **Keep in Python** | P3 | N/A |
| **LLM Integration** | Python | **Keep in Python** | P3 | N/A |
| **URL Fetcher** | Python | Rust (reqwest) | P2 | Low |

---

## 3. Rust Core Extended Structure

```
mnemosyne-core/
├── Cargo.toml
├── src/
│   ├── lib.rs              # PyO3 module entry point
│   ├── cli/
│   │   ├── mod.rs
│   │   ├── commands.rs     # CLI command definitions
│   │   └── args.rs         # Argument parsing
│   ├── db/
│   │   ├── mod.rs
│   │   ├── connection.rs   # SQLite connection pool
│   │   ├── entities.rs     # Entity CRUD
│   │   ├── relations.rs    # Relation CRUD
│   │   └── migrations.rs   # Schema management
│   ├── graph/
│   │   ├── mod.rs
│   │   ├── query.rs       # Graph query engine
│   │   ├── traversal.rs   # Path finding, BFS/DFS
│   │   └── metrics.rs     # Graph statistics
│   ├── wiki/
│   │   ├── mod.rs
│   │   ├── builder.rs     # Wiki page generation
│   │   ├── linker.rs      # Wiki link resolution
│   │   ├── frontmatter.rs # YAML generation
│   │   └── rebuild.rs     # Parallel rebuild
│   ├── ingest/
│   │   ├── mod.rs
│   │   ├── file.rs        # File ingestion
│   │   ├── hash.rs        # Content hashing
│   │   └── sync.rs        # Hash-based incremental sync
│   ├── extraction/
│   │   ├── mod.rs
│   │   ├── tree_sitter/   # Tree-sitter native
│   │   │   ├── mod.rs
│   │   │   ├── python.rs
│   │   │   ├── js_ts.rs
│   │   │   ├── go.rs
│   │   │   └── rust.rs
│   │   └── ast.rs        # AST utilities
│   ├── fts/
│   │   ├── mod.rs
│   │   └── search.rs      # Full-text search
│   ├── http/
│   │   ├── mod.rs
│   │   └── client.rs      # HTTP client for URL fetching
│   └── bridge/
│       ├── mod.rs
│       └── subagent.rs    # IPC to Python ML agent
└── benches/               # Performance benchmarks
```

---

## 4. Python Subagent Structure

```
mnemosyne-ml-agent/           # NEW: Separate Python package
├── pyproject.toml
├── src/
│   ├── __init__.py
│   ├── main.py               # CLI entry point
│   ├── semantic/
│   │   ├── gliner.py         # GLiNER2 NER
│   │   ├── rebel.py          # REBEL relation extraction
│   │   └── torch_utils.py    # Torch utilities
│   ├── llm/
│   │   ├── anthropic.py     # Claude API
│   │   ├── openai.py        # OpenAI API
│   │   └── synthesis.py     # LLM synthesis
│   └── ipc/
│       ├── mod.rs
│       ├── server.py         # JSON-RPC or stdio server
│       └── protocol.py       # Message protocol definition
└── tests/
```

---

## 5. Communication Protocol

### Rust → Python (Subprocess/IPC)

```json
// Request: Entity extraction
{
  "version": "1.0",
  "type": "extract_entities",
  "text": "...",
  "options": {
    "labels": ["PERSON", "ORG"],
    "model": "gliner-small-v1"
  }
}

// Response
{
  "version": "1.0",
  "type": "extract_entities_response",
  "entities": [
    {"id": "e1", "label": "John", "type": "PERSON", "confidence": 0.95, ...}
  ],
  "relations": [...],
  "metadata": {
    "processing_time_ms": 123,
    "model": "gliner-small-v1"
  }
}
```

### Communication Methods

| Method | Use Case | Pros | Cons |
|--------|----------|------|------|
| **stdio (JSON lines)** | Single requests | Simple | No concurrent requests |
| **Unix socket** | Local IPC | Fast, supports concurrency | Platform-specific |
| **HTTP (localhost)** | Complex workflows | Standard, debuggable | Overhead |
| **Shared memory** | Large text transfer | Fastest | Complex |

**Recommendation**: Start with **stdio JSON-RPC**, upgrade to Unix socket if needed.

---

## 6. Migration Milestones

### Milestone 1: Foundation ✅
- [x] Current `mnemosyne-core` analysis
- [ ] Define Rust core interfaces
- [ ] Design IPC protocol
- [ ] Set up project structure

**Success Criteria**: Interface documentation complete, proof-of-concept IPC working

### Milestone 2: Wiki & Graph (P1)
- [ ] `wiki/` module → Rust
- [ ] `graph/` module → Rust
- [ ] Benchmark vs Python

**Success Criteria**: 2-3x faster wiki rebuild, graph queries

### Milestone 3: CLI & Ingest (P1)
- [ ] CLI → Rust (clap)
- [ ] Core ingest → Rust
- [ ] Backward compatibility

**Success Criteria**: CLI parity, drop-in replacement

### Milestone 4: Tree-sitter & FTS (P2)
- [ ] Tree-sitter → Rust native
- [ ] FTS optimization

**Success Criteria**: Zero-LLM extraction in pure Rust

### Milestone 5: Python Subagent (P3)
- [ ] Split out `mnemosyne-ml-agent`
- [ ] IPC implementation
- [ ] Integration testing

**Success Criteria**: Rust core calling Python for ML, end-to-end working

---

## 7. Performance Targets

| Operation | Current (Python) | Target (Rust) | Improvement |
|-----------|------------------|---------------|-------------|
| Wiki rebuild (100 pages) | ~5s | ~1-2s | 2.5-5x |
| Graph query (10k entities) | ~500ms | ~100-200ms | 2.5-5x |
| Ingest (100 files) | ~30s | ~10s | 3x |
| Tree-sitter parse | ~2s/file | ~0.5s/file | 4x |

---

## 8. Compatibility Strategy

### Phase 1: Coexistence
- Python CLI with Rust core backend (PyO3)
- Drop-in replacement, no user-facing changes

### Phase 2: Dual CLI
- `mnemosyne` (Rust native) - primary
- `mnemosyne-python` (legacy) - deprecated

### Phase 3: Full Transition
- Pure Rust binary
- Python only for ML subagent

---

## 9. Development Workflow

### For Rust Core
```bash
cd mnemosyne-core
cargo build --release
cargo test
cargo bench
```

### For Python Subagent
```bash
cd mnemosyne-ml-agent
pip install -e .
pytest
```

### Integration
```bash
# Run tests
cargo test --features python-integration
pytest tests/integration/

# Run benchmark
cargo bench --bench wiki_rebuild
```

---

## 10. Open Questions

| ID | Question | Proposed Answer |
|----|----------|-----------------|
| OQ-1 | Should we use an existing RPC library? | Start with manual JSON-RPC, consider `tarpc` later |
| OQ-2 | How to handle ML model loading overhead? | Lazy load, keep process warm for batch requests |
| OQ-3 | Should we support remote ML agents? | Yes, protocol should be network-transparent |
| OQ-4 | How to handle errors across language boundary? | Structured error codes with Python traceback attachment |

---

## Appendix A: References

- [PyO3 Documentation](https://pyo3.rs/)
- [Rust Performance Guidelines](https://doc.rust-lang.org/nomicon/)
- [Tree-sitter Rust Bindings](https://docs.rs/tree-sitter/)
- [Rayon Parallelism](https://docs.rs/rayon/)

---

## Appendix B: Terminology

| Term | Definition |
|------|------------|
| **Rust Core** | High-performance Rust implementation of core Mnemosyne functionality |
| **Python Subagent** | Separate Python process handling ML/SLM operations |
| **IPC** | Inter-Process Communication between Rust and Python |
| **PyO3 Bridge** | Python-callable Rust functions via PyO3 bindings |

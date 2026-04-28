# Mnemosyne Knowledge Graph

Local-first, zero-API-cost knowledge memory system for AI agents. Provides persistent, compounding knowledge across three domains: **daily life**, **coding**, and **legal**.

Based on Google's Gemini Universal Temporal Knowledge Graph research and Andrej Karpathy's insight: *"Obsidian is the IDE, the language model is the programmer, and the wiki is the codebase."*

## Quality Status

| Metric | Status |
|--------|--------|
| Tests | 413 passed, 2 skipped |
| Type Safety | mypy 0 errors |
| Lint | ruff 0 violations |
| Coverage | 81%+ |
| SPECs | 8 completed, 0 in progress |

## Architecture

```
Raw Source Layer (Immutable)
       ↓
Wiki Layer (Markdown + [[wiki-links]])
       ↓
Schema Layer (CLAUDE.md / AGENTS.md)
       ↓
Knowledge Graph (SQLite + NetworkX)
```

**Four-layer extraction pipeline:**

| Layer | Technology | Cost | Hardware |
|-------|-----------|------|----------|
| Deterministic | Tree-sitter AST, SpaCy | $0 | CPU only |
| Semantic | GLiNER2 NER, REBEL | $0 | CPU / small GPU |
| Synthesis | Llama-3-8B / GPT-4o | Optional | GPU / Cloud |
| Wiki | Markdown + wiki-links | $0 | Any |

## Installation

```bash
# Core only
pip install -e .

# With deterministic extraction (tree-sitter)
pip install -e ".[deterministic]"

# With semantic extraction (GLiNER2, torch)
pip install -e ".[semantic]"

# Development (lint, type-check, test)
pip install -e ".[dev]"

# Everything
pip install -e ".[all]"
```

## Quick Start

```bash
# Install with all dependencies
pip install -e ".[all]"

# Extract code entities from a project
mnemosyne-extract ~/my-project --domain coding --format json

# Run full extraction pipeline
python -m mnemosyne.extraction.pipeline --domain coding --source ~/my-project

# Query the knowledge graph
mnemosyne query --stats
python -m mnemosyne.graph.knowledge_graph --query "search:authenticate"

# Extract with session scope (tracks extraction context)
python -m mnemosyne.extraction.pipeline \
  --domain coding --source ~/my-project \
  --scope-id impl-session --source-channel vscode \
  --incremental
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `mnemosyne --version` | Show package version |
| `mnemosyne query --stats` | Graph statistics |
| `mnemosyne query "search:term"` | Fuzzy entity search |
| `mnemosyne extract ~/path` | Extract from source |
| `mnemosyne-extract ~/path --format wiki` | Wiki-formatted output |
| `mnemosyne-query --stats` | Standalone graph query |

### Extraction Pipeline Options

```bash
python -m mnemosyne.extraction.pipeline \
  --domain coding \          # coding | daily | legal
  --source ~/path \          # File or directory
  --format json \            # json | wiki | summary
  --scope-id SESSION_ID \    # Attach scope to entities
  --source-channel CHANNEL \ # Tag extraction source
  --db-path ~/kg.db \        # Custom DB path
  --no-semantic \            # Skip semantic layer
  --incremental              # Skip unchanged files
```

### Deterministic Extraction (Zero LLM)

```bash
# Single file
python -m mnemosyne.extraction.deterministic.code_parser ~/project/main.py

# Directory with wiki output
python -m mnemosyne.extraction.deterministic.code_parser ~/project --format wiki

# With session scope
python -m mnemosyne.extraction.deterministic.code_parser ~/project \
  --scope-id impl-session --source-channel vscode
```

Supported languages: **Python, JavaScript, TypeScript, TSX, Go, Rust**

## Python API

### Entity Extraction

```python
from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor
from pathlib import Path

extractor = TreeSitterExtractor()

# Extract from a single file
result = extractor.extract_file_full(Path("main.py"))
print(f"Found {len(result.entities)} entities")
print(f"Imports: {len(result.imports)}")
print(f"Calls: {len(result.calls)}")

# Extract from a directory
entities = extractor.extract_directory(Path("src/"), scope_id="my-session")

# Convert to wiki format
print(extractor.to_wiki_format(result.entities, result.imports, result.calls))
```

### Semantic Extraction

```python
from mnemosyne.extraction.semantic.slm_extractor import SemanticExtractor

with SemanticExtractor() as extractor:
    result = extractor.extract(
        "John Smith works at Google Inc",
        ["PERSON", "ORGANIZATION"],
        scope_id="session-1",
        source_channel="cli",
    )
    # result = {entities: [...], relations: [...], token_cost: N, extraction_method: "local_slm"}
```

### Knowledge Graph Queries

```python
from mnemosyne.graph.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()

# Statistics
stats = kg.get_stats()

# Search entities
results = kg.query("search:authenticate")

# Entity by type and name
results = kg.query("entity:function[parse_config]")

# Relations
results = kg.query("relation:calls")

# Shortest path between entities
results = kg.query("path:get_user,authenticate")

# Session-scoped queries
results = kg.query("entity:function[*]@session:impl-session")
```

### Scope Management

```python
from mnemosyne.graph.scope_manager import ScopeManager

sm = ScopeManager()

# Create hierarchical scopes
sm.create_scope("project-x", scope_type="project")
sm.create_scope("feature-auth", parent_id="project-x", scope_type="feature")
sm.create_scope("session-1", parent_id="feature-auth", scope_type="session")

# Query scope tree
children = sm.get_children("project-x")
lineage = sm.get_lineage("session-1")
```

## Domain Schemas

### Daily Life

| Entity | Key Fields | Use Case |
|--------|-----------|----------|
| `task` | deadline, priority, status | Task management |
| `person` | role, contact, interaction history | Contact tracking |
| `place` | type, address, visit frequency | Location awareness |
| `event` | datetime, duration, participants | Calendar |
| `habit` | frequency, time, streak | Behavior tracking |
| `preference` | category, value, confidence | Personalization |
| `note` | title, content, tags | General notes |

### Coding

| Entity | Key Fields | Use Case |
|--------|-----------|----------|
| `function` | signature, language, complexity | Code navigation |
| `class` | methods, attributes, inheritance | Architecture |
| `module` | exports, imports | Dependency tracking |
| `api` | endpoint, method, auth | API docs |
| `bug` | severity, status, affected functions | Bug tracking |
| `feature` | status, priority, implements | Feature tracking |
| `test` | type, coverage, status | QA |
| `dependency` | version, vulnerabilities | Supply chain |

### Legal

| Entity | Key Fields | Use Case |
|--------|-----------|----------|
| `statute` | jurisdiction, code, effective_date | Law reference |
| `clause` | obligation_type, content | Contract analysis |
| `case` | court, date, holding, reasoning | Precedent lookup |
| `party` | type, role, counsel | Party management |
| `obligation` | description, deadline | Compliance tracking |
| `deadline` | date, type, consequence | Deadline alerts |
| `contract` | parties, effective_date, status | Contract lifecycle |

## Wiki Link Syntax

| Syntax | Meaning |
|--------|---------|
| `[[note-name]]` | Link to a Joplin note |
| `[[entity:type:name]]` | Link to knowledge graph entity |
| `[[entity:type:name@session:s1]]` | Entity in specific session |
| `[[entity:type:name@project:p1@channel:code]]` | Entity with combined scope |
| `[[graph:query]]` | Embed graph query result |

## Directory Structure

```
mnemosyne-knowledge-graph/
├── mnemosyne/                    # Main Python package
│   ├── __init__.py               # Public API exports
│   ├── __main__.py               # python -m mnemosyne entry
│   ├── cli.py                    # Main CLI (query, extract)
│   ├── graph/                    # Knowledge graph engine
│   │   ├── cli.py                # Graph query CLI
│   │   ├── knowledge_graph.py    # SQLite + NetworkX
│   │   └── scope_manager.py      # Hierarchical scopes
│   ├── extraction/               # Extraction pipelines
│   │   ├── cli.py                # Extraction CLI
│   │   ├── pipeline.py           # 3-layer orchestration
│   │   ├── pipeline_types.py     # Type definitions
│   │   ├── deterministic/        # Zero-LLM layer
│   │   │   ├── code_parser.py    # Tree-sitter extraction
│   │   │   ├── types.py          # ParseResult, ImportEntity, CallRelation
│   │   │   └── languages/        # Per-language extractors
│   │   │       ├── base.py       # LanguageExtractor protocol
│   │   │       ├── python_extractor.py
│   │   │       ├── javascript_extractor.py
│   │   │       ├── go_extractor.py
│   │   │       └── rust_extractor.py
│   │   ├── semantic/             # Local SLM layer
│   │   │   └── slm_extractor.py  # GLiNER2 + REBEL
│   │   └── synthesis/            # Optional LLM layer
│   ├── raw/                      # Immutable source documents
│   ├── wiki/                     # Extracted knowledge
│   └── schema/                   # Domain schemas
├── tests/                        # 413 tests
├── joplin-plugin/                # Joplin plugin (TypeScript)
├── pyproject.toml                # PEP 621 config
├── CHANGELOG.md                  # Version history
└── CLAUDE.md                     # System prompt
```

## Key Features

- **Zero API Cost**: Tree-sitter AST parsing (6 languages), local SLMs for NLP
- **Knowledge Compounding**: Wiki-layer accumulates knowledge across extractions
- **Temporal Tracking**: Entity version history with timestamps
- **Session Scopes**: Hierarchical project/topic/session scoping
- **Incremental Extraction**: SHA-256 content hash tracking
- **Multi-domain**: Coding, daily life, and legal schemas
- **Protocol-based**: `LanguageExtractor` protocol for extensible language support
- **Production Ready**: mypy strict, ruff clean, 413 tests, 81%+ coverage

# Universal Temporal Knowledge Graph System for AI Agents

Based on research from Google's Gemini knowledge graph architecture, this system provides a **local-first, zero-API-cost** knowledge memory for AI agents spanning daily life, coding, and legal domains.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    RAW SOURCE LAYER (Immutable)                      │
│         ~/agent-memory/mnemosyne/raw/{daily,coding,legal}             │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Extraction Pipeline (never modifies)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    WIKI LAYER (Knowledge Binary)                     │
│         ~/agent-memory/mnemosyne/wiki/{daily,coding,legal}            │
│         Human-readable Markdown + [[wiki-links]]                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Schema Governance
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 SCHEMA LAYER (CLAUDE.md / AGENTS.md)                 │
│         ~/agent-memory/mnemosyne/schema/{domain}.md                   │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Graph Database
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              KNOWLEDGE GRAPH (SQLite + NetworkX)                     │
│         ~/agent-memory/mnemosyne/graph/{entities,relations}.db        │
└─────────────────────────────────────────────────────────────────────┘
```

## Domain Coverage

| Domain | Entity Types | Use Cases |
|--------|-------------|-----------|
| **Daily Life** | `task`, `person`, `place`, `event`, `habit`, `preference`, `note` | Scheduling, contacts, routines |
| **Coding** | `function`, `class`, `module`, `api`, `bug`, `feature`, `test`, `dependency` | Code search, dependency tracking, bug correlation |
| **Legal** | `statute`, `clause`, `case`, `party`, `obligation`, `deadline`, `contract` | Compliance, contract analysis, precedent lookup |

## Installation

```bash
# Basic install (core dependencies only)
pip install -e .

# With deterministic extraction (tree-sitter, spacy)
pip install -e ".[deterministic]"

# With semantic extraction (GLiNER2, torch)
pip install -e ".[semantic]"

# Development setup
pip install -e ".[dev]"

# Everything
pip install -e ".[all]"
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `mnemosyne --version` | Show package version |
| `mnemosyne query --stats` | Query graph statistics |
| `mnemosyne extract ~/path` | Extract entities from source |
| `mnemosyne-query --stats` | Graph query CLI (standalone) |
| `mnemosyne-extract --help` | Extraction CLI (standalone) |
| `python -m mnemosyne.graph.knowledge_graph --stats` | Module-based CLI |
| `python -m mnemosyne.extraction.pipeline --domain coding --source ~/path` | Full extraction pipeline |

## Quick Start

```bash
# Install the package
pip install -e .

# Or with all optional dependencies
pip install -e ".[all]"

# Query the knowledge graph
mnemosyne-query --stats
python -m mnemosyne.graph.knowledge_graph --query "search:parse_config"

# Extract knowledge using the full pipeline
python -m mnemosyne.extraction.pipeline --domain coding --source ~/my-project

# Extract with session scope and incremental mode
python -m mnemosyne.extraction.pipeline --domain coding --source ~/my-project --scope-id my-session --incremental

# Extract using deterministic layer only (tree-sitter AST parsing)
python -m mnemosyne.extraction.deterministic.code_parser ~/my-project --format wiki

# Start Joplin plugin
cd joplin-plugin/knowledge-graph
npm install && npm run build
```

## Directory Structure

```
mnemosyne-knowledge-graph/
├── mnemosyne/            # Main Python package
│   ├── __init__.py       # Package root with version and public API
│   ├── cli.py            # Main CLI entry point
│   ├── graph/            # Graph database + query engine
│   │   ├── cli.py        # Graph query CLI
│   │   ├── knowledge_graph.py
│   │   └── scope_manager.py
│   ├── extraction/       # Extraction pipelines
│   │   ├── cli.py        # Extraction CLI
│   │   ├── pipeline.py   # End-to-end extraction pipeline
│   │   ├── pipeline_types.py  # Pipeline type definitions
│   │   ├── deterministic/  # Tree-sitter AST parsing, SpaCy (zero-LLM)
│   │   │   └── languages/  # Language-specific extractors (Python, JS, TS, TSX, Go, Rust)
│   │   ├── semantic/       # GLiNER2, REBEL (local SLM)
│   │   └── synthesis/      # High-level synthesis (optional LLM)
│   ├── raw/              # Immutable source documents
│   ├── wiki/             # Extracted knowledge (markdown + wiki-links)
│   └── schema/           # Domain schemas
├── tests/                # Test suite
├── joplin-plugin/        # Joplin plugin (TypeScript)
├── pyproject.toml        # PEP 621 package configuration
└── CLAUDE.md             # Main system prompt
```

## Key Features

- **Zero API Cost**: Tree-sitter AST parsing for code (6 languages), local SLMs for NLP
- **Knowledge Compounding**: Wiki-layer accumulates knowledge across extractions
- **Temporal Tracking**: Entities and relations maintain version history
- **Schema-driven**: Modify `CLAUDE.md` to change graph structure
- **Joplin Integration**: Obsidian-like wiki-link experience with Joplin
- **Incremental Extraction**: SHA-256 content hash tracking for efficient updates
- **Multi-domain Support**: Coding, daily life, and legal knowledge graphs
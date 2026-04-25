# Universal Temporal Knowledge Graph System for AI Agents

Based on research from Google's Gemini knowledge graph architecture, this system provides a **local-first, zero-API-cost** knowledge memory for AI agents spanning daily life, coding, and legal domains.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    RAW SOURCE LAYER (Immutable)                      │
│         ~/agent-memory/core/raw/{daily,coding,legal}                 │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Extraction Pipeline (never modifies)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    WIKI LAYER (Knowledge Binary)                     │
│         ~/agent-memory/core/wiki/{daily,coding,legal}                │
│         Human-readable Markdown + [[wiki-links]]                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Schema Governance
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 SCHEMA LAYER (CLAUDE.md / AGENTS.md)                 │
│         ~/agent-memory/core/schema/{domain}.md                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Graph Database
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              KNOWLEDGE GRAPH (SQLite + NetworkX)                     │
│         ~/agent-memory/core/graph/{entities,relations}.db            │
└─────────────────────────────────────────────────────────────────────┘
```

## Domain Coverage

| Domain | Entity Types | Use Cases |
|--------|-------------|-----------|
| **Daily Life** | `task`, `person`, `place`, `event`, `habit`, `preference`, `note` | Scheduling, contacts, routines |
| **Coding** | `function`, `class`, `module`, `api`, `bug`, `feature`, `test`, `dependency` | Code search, dependency tracking, bug correlation |
| **Legal** | `statute`, `clause`, `case`, `party`, `obligation`, `deadline`, `contract` | Compliance, contract analysis, precedent lookup |

## Quick Start

```bash
# Install dependencies
cd ~/agent-memory
pip install -r requirements.txt

# Extract knowledge from raw sources
python -m core.extraction.pipeline --domain all

# Query the knowledge graph
python -m core.graph.query --entity "function:parse_config"

# Start Joplin plugin
cd joplin-plugin/knowledge-graph
npm install && npm run build
```

## Directory Structure

```
agent-memory/
├── core/
│   ├── raw/              # Immutable source documents
│   ├── wiki/             # Extracted knowledge (markdown + wiki-links)
│   ├── schema/           # Domain schemas (CLAUDE.md, AGENTS.md)
│   ├── extraction/       # Extraction pipelines
│   │   ├── deterministic/  # Tree-sitter, SpaCy (zero-LLM)
│   │   ├── semantic/       # GLiNER2, REBEL (local SLM)
│   │   └── synthesis/      # High-level synthesis (optional LLM)
│   └── graph/            # Graph database + query engine
├── joplin-plugin/        # Joplin plugin for Obsidian-like experience
├── agents/               # Agent-specific memory configs
│   ├── daily-life/
│   ├── coding/
│   └── legal/
└── CLAUDE.md             # Main system prompt
```

## Key Features

- **Zero API Cost**: Deterministic parsing for code, local SLMs for NLP
- **Knowledge Compounding**: Wiki-layer accumulates knowledge across extractions
- **Temporal Tracking**: Entities and relations maintain version history
- **Schema-driven**: Modify `CLAUDE.md` to change graph structure
- **Joplin Integration**: Obsidian-like wiki-link experience with Joplin
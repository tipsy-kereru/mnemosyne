# Architecture: Mnemosyne Knowledge Graph

## Directory Layout

```
mnemosyne-knowledge-graph/
├── core/
│   ├── graph/
│   │   ├── __init__.py
│   │   └── knowledge_graph.py    # KnowledgeGraph class (SQLite + NetworkX)
│   ├── extraction/
│   │   ├── deterministic/
│   │   │   └── code_parser.py    # Tree-sitter AST extraction (Python/Go/JS/Rust)
│   │   └── semantic/
│   │       └── slm_extractor.py  # GLiNER2 NER + REBEL relation extraction
│   └── schema/
│       ├── daily-life.md         # Daily life domain schema
│       ├── coding.md             # Coding domain schema
│       └── legal.md              # Legal domain schema
├── joplin-plugin/
│   └── knowledge-graph/
│       ├── src/
│       │   ├── index.ts          # KnowledgeGraphPlugin main class
│       │   └── content_script.ts # Wiki-link processing
│       └── webpack.config.js
├── CLAUDE.md                     # System schema + usage docs
├── AGENTS.md                     # Agent API reference
├── README.md                     # Project overview
└── requirements.txt              # Python dependencies
```

## Core Components

### KnowledgeGraph (knowledge_graph.py)
Central graph database class. SQLite for persistence, NetworkX for analysis.

Key methods:
- `add_entity()`, `add_relation()` — CRUD operations
- `query()` — Unified query language (entity/relation/path/search)
- `get_entity_history()` — Temporal change tracking
- `_build_networkx()` — SQLite → NetworkX graph construction
- `get_stats()` — Graph statistics

### Extraction Pipeline (3-layer)
1. **Deterministic** (code_parser.py): Tree-sitter AST — zero cost, 71.5x token reduction
2. **Semantic** (slm_extractor.py): GLiNER2 + REBEL — local SLM, zero API cost
3. **Synthesis**: Optional LLM layer for complex queries

### Joplin Plugin (index.ts)
Obsidian-like experience for knowledge navigation:
- Auto entity extraction from notes
- Domain detection (daily/coding/legal)
- Wiki-link processing ([[wiki-links]])
- Graph visualization
- Search with results display

### Schema System (core/schema/*.md)
Declarative Markdown schemas defining entity types and relationships per domain:
- 7 entity types in daily-life (task, person, place, event, habit, preference, note)
- 8 entity types in coding (function, class, module, api, bug, feature, test, dependency)
- 7 entity types in legal (statute, clause, case, party, obligation, deadline, contract)

## Data Flow

```
Raw files → Extraction Pipeline → KnowledgeGraph (SQLite + NetworkX)
                                    ↓
                              Joplin Plugin (wiki-links, graph view)
```

## Dependencies

- networkx — Graph analysis
- SQLAlchemy — ORM
- tree-sitter — Code AST parsing (optional)
- SpaCy — NLP (optional)
- GLiNER — NER model (optional)
- REBEL — Relation extraction (optional)

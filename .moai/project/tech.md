# Technology Stack: Mnemosyne Knowledge Graph

## Primary Languages

- **Python 3**: Core graph engine, extraction pipeline, schemas
- **TypeScript**: Joplin plugin (Obsidian-like UI)

## Key Libraries

| Library | Purpose | Required |
|---------|---------|----------|
| networkx | Graph analysis (BFS, shortest path, community detection) | Yes |
| SQLAlchemy | ORM for SQLite persistence | Yes |
| uuid | Entity ID generation | Yes |
| PyYAML | Schema parsing from Markdown files | Yes |
| python-dateutil | Temporal parsing | Yes |
| tree-sitter | Code AST parsing (Python/Go/JS/Rust) | Optional |
| SpaCy | NLP rule-based extraction | Optional |
| GLiNER | Local NER model | Optional |
| torch | SLM runtime for GLiNER/REBEL | Optional |

## Storage

- **SQLite**: Primary persistence layer for entities, relations, temporal history
- **NetworkX**: In-memory graph for analysis (built from SQLite on demand)
- **Markdown files**: Schema definitions in core/schema/

## Schema Format

Declarative Markdown with YAML-like structure:
- Entity definitions with properties
- Relationship type definitions with source/target
- Extraction rules per domain

Parsed by PyYAML at runtime to configure graph structure.

## Design Principles

1. **Local-first**: No cloud API calls required
2. **Zero API cost**: Deterministic + local SLM extraction
3. **Immutable raw layer**: Sources never modified
4. **Declarative schemas**: Graph structure changed via text file edits
5. **Temporal tracking**: All entity changes tracked with timestamps

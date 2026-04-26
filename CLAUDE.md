# AI Agent Universal Temporal Knowledge Graph System

## System Overview

This is a local-first, zero-API-cost knowledge memory system for AI agents. It provides persistent, compounding knowledge across three domains: **daily life**, **coding**, and **legal**.

Based on Google's Gemini Universal Temporal Knowledge Graph research. Quote from Andrej Karpathy: *"Obsidian is the IDE, the language model is the programmer, and the wiki is the codebase."*

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

## Directory Structure

```
~/agent-memory/
├── mnemosyne/
│   ├── raw/                    # Immutable source documents
│   │   ├── daily/
│   │   ├── coding/
│   │   └── legal/
│   ├── wiki/                   # Extracted knowledge (human-readable)
│   │   ├── daily/
│   │   ├── coding/
│   │   └── legal/
│   ├── schema/                 # Domain schemas
│   │   ├── daily-life.md
│   │   ├── coding.md
│   │   └── legal.md
│   ├── extraction/             # Extraction pipelines
│   │   ├── deterministic/      # Tree-sitter, SpaCy (zero-LLM)
│   │   ├── semantic/           # GLiNER2, REBEL (local SLM)
│   │   └── synthesis/          # Optional LLM synthesis
│   └── graph/                  # Graph database
│       └── knowledge.db
├── joplin-plugin/              # Joplin plugin for Obsidian-like experience
└── agents/                     # Agent-specific configs
```

## Domain Schemas

### Daily Life Entities
- `task`: Action items with deadline, priority, status
- `person`: Contacts with relationship and interaction history
- `place`: Locations (home, work, public, online)
- `event`: Calendar events and appointments
- `habit`: Recurring behavior patterns
- `preference`: User preferences with confidence scores
- `note`: General reference notes

### Coding Entities
- `function`: Functions/methods with signature, language, complexity
- `class`: Classes/structs with methods and attributes
- `module`: Packages, namespaces, crates
- `api`: API endpoints (REST, GraphQL, gRPC)
- `bug`: Bug reports with severity and affected functions
- `feature`: Feature requests with implementation tracking
- `test`: Test cases with coverage information
- `dependency`: External libraries with version tracking

### Legal Entities
- `statute`: Laws with jurisdiction and code citations
- `clause`: Document sections with obligation types
- `case`: Court cases with holdings and reasoning
- `party`: Legal entities (individuals, corporations)
- `obligation`: Legal duties and requirements
- `deadline`: Time limits for filings, responses, payments
- `contract`: Legal agreements with clauses and status

## Usage Commands

### Extraction

```bash
# Extract code entities from a directory using tree-sitter AST parsing (zero LLM)
python -m mnemosyne.extraction.deterministic.code_parser ~/my-project --format wiki

# Extract with session scope
python -m mnemosyne.extraction.deterministic.code_parser ~/my-project --scope-id impl-session --source-channel vscode

# Extract semantic entities using local SLM
python -m mnemosyne.extraction.semantic.slm_extractor --text "John works at Google" --entities PERSON ORGANIZATION

# Extract semantic entities with session scope
python -m mnemosyne.extraction.semantic.slm_extractor --text "John works at Google" --entities PERSON ORGANIZATION --scope-id session-1 --source-channel discord

# Run full extraction pipeline (3-layer: deterministic → semantic → synthesis)
python -m mnemosyne.extraction.pipeline --domain coding --source ~/my-project

# Run pipeline with session scope and incremental extraction
python -m mnemosyne.extraction.pipeline --domain coding --source ~/my-project --scope-id my-session --incremental

# Run pipeline with custom report format
python -m mnemosyne.extraction.pipeline --domain coding --source ~/my-project --report-format json
```

### Knowledge Graph Query

```bash
# Query entities
python -m mnemosyne.graph.knowledge_graph --query "entity:function[parse_config]"

# Query relations
python -m mnemosyne.graph.knowledge_graph --query "relation:calls"

# Find path between entities
python -m mnemosyne.graph.knowledge_graph --query "path:get_user,authenticate"

# Session-aware queries
python -m mnemosyne.graph.knowledge_graph --query "entity:function[*]@session:impl-session"
python -m mnemosyne.graph.knowledge_graph --query "entity:task[*]@project:snake-game"
python -m mnemosyne.graph.knowledge_graph --query "relation:calls@session:s1@channel:code"

# Search
python -m mnemosyne.graph.knowledge_graph --query "search:authentication"

# Stats
python -m mnemosyne.graph.knowledge_graph --stats
```

### Joplin Plugin

```bash
cd ~/agent-memory/joplin-plugin/knowledge-graph
npm install
npm run build
# Load the .jpl file in Joplin settings
```

## Wiki Link Syntax

Use `[[wiki-links]]` for cross-referencing:

- `[[note-name]]` - Link to a Joplin note
- `[[entity:type:name]]` - Link to a knowledge graph entity
- `[[entity:type:name@session:my-session]]` - Link to entity in specific session scope
- `[[entity:type:name@project:my-project@channel:code]]` - Link with combined scope modifiers
- `[[graph:query]]` - Link to a graph query result

## Knowledge Compounding

The system achieves **knowledge compounding** by:

1. **Immutable Raw Layer**: Sources are never modified
2. **Re-compilation**: When extraction models improve, full graph can be regenerated
3. **Version History**: All entity changes are tracked temporally
4. **Wiki Layer**: Extracted knowledge accumulates in human-readable format

## Extraction Pipeline

### Layer 1: Deterministic Syntax Parsing (Zero LLM)
- Tree-sitter AST parsing for code (Python, JavaScript, TypeScript, TSX, Go, Rust)
- Protocol-based architecture with language-specific extractors
- Import graph and call graph extraction
- SpaCy rule-based for natural language
- Token reduction: 71.5x vs traditional chunking
- Cost: $0

### Layer 2: Local SLM Semantic Extraction
- GLiNER2 for NER (runs on CPU)
- REBEL for relation extraction
- Schema-driven custom entity types
- No fine-tuning required
- Multi-domain routing (coding, daily, legal)

### Layer 3: Optional LLM Synthesis (Higher Cost)
- Llama-3-8B / GPT-4o / Claude for complex queries
- Used only when deterministic methods insufficient

## Best Practices

1. **Always extract before storing**: Run extraction pipeline on raw sources
2. **Use domain-specific schemas**: Match entity types to content domain
3. **Link entities**: Use [[wiki-links]] to create cross-references
4. **Query before asking**: Check knowledge graph before assuming facts
5. **Update schemas**: Modify CLAUDE.md to evolve the graph structure

## Example Workflow

```
1. User asks: "What functions call the authenticate function?"

2. Agent queries: entity:function[authenticate]
   → Finds function ID

3. Agent queries: relation:calls(?, authenticate_id)
   → Finds all callers

4. Agent returns: List of functions with file paths and line numbers
```

## Limitations

- Deterministic tree-sitter parsing works best for well-structured code (6 supported languages)
- Natural language extraction requires SpaCy models
- Local SLM models need sufficient RAM (8GB+ recommended)
- Graph queries require exact entity names (use search:* for fuzzy)
- Pipeline extraction requires domain-specific schemas in CLAUDE.md
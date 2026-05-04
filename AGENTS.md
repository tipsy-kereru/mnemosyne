# AI Agent Knowledge Memory - Usage Guide

## Quick Reference

When an AI agent needs to use knowledge from this system, follow these patterns:

### Query the Knowledge Graph

```python
from core.graph.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()

# Find entities
result = kg.query("entity:function[parse_config]")

# Find relations
result = kg.query("relation:calls")

# Find connections
result = kg.query("path:get_user,authenticate")

# Search
result = kg.query("search:authentication")
```

### Extract from Source Code

```python
from core.extraction.deterministic.code_parser import TreeSitterExtractor

extractor = TreeSitterExtractor()
entities = extractor.extract_directory(Path("~/my-project"))
print(extractor.to_wiki_format(entities))
```

### Semantic Extraction (NLP)

```python
from core.extraction.semantic.slm_extractor import SemanticExtractor

extractor = SemanticExtractor()
result = extractor.extract(
    "John Smith works at Google in San Francisco.",
    entity_types=['PERSON', 'ORGANIZATION', 'LOCATION']
)
```

## Domain-Specific Patterns

### Daily Life
- Query tasks: `entity:task[.*]` then filter by status
- Find people: `search:John`
- Upcoming events: `entity:event[.*]` sorted by datetime

### Coding
- Find function callers: `relation:calls(?,function_id)`
- Track bugs: `entity:bug[.*]` filtered by severity
- Dependencies: `entity:dependency[requests]`

### Legal
- Find precedents: `entity:case[.*]` citing specific statute
- Track obligations: `relation:creates(?,party_id)`
- Deadlines: `entity:deadline[.*]` sorted by date

## Wiki Link Syntax

In notes and documents, use:

| Syntax | Meaning |
|--------|---------|
| `[[note-name]]` | Link to Joplin note |
| `[[entity:function:authenticate]]` | Link to knowledge graph entity |
| `[[graph:search:security]]` | Link to graph query |

## Adding New Knowledge

1. Place raw source in `core/raw/{domain}/`
2. Run extraction: `python -m core.extraction.pipeline --domain {domain}`
3. Knowledge appears in wiki layer and graph database
4. Link from notes using `[[wiki-links]]`

## Session-Aware Extraction

Extract entities with session context for scoped knowledge graphs:

```python
from core.extraction.deterministic.code_parser import TreeSitterExtractor

extractor = TreeSitterExtractor()

# Extract with session scope
entities = extractor.extract_file(
    Path("src/main.py"),
    scope_id="impl-session",
    source_channel="vscode"
)

# Directory extraction with scope
entities = extractor.extract_directory(
    Path("~/my-project"),
    scope_id="proj-alpha",
    source_channel="cli"
)
```

```python
from core.extraction.semantic.slm_extractor import SemanticExtractor

extractor = SemanticExtractor()
result = extractor.extract(
    "John Smith works at Google.",
    entity_types=['PERSON', 'ORGANIZATION'],
    scope_id="session-1",
    source_channel="discord"
)
# All entities/relations in result have scope_id and source_channel set
```

## Session-Aware Queries

Query entities within a specific session or project scope:

```python
from core.graph.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()

# Query within session scope
result = kg.query("entity:function[*]@session:impl-session")

# Query within project scope
result = kg.query("entity:task[*]@project:snake-game")

# Filter by channel
result = kg.query("entity:function[*]@channel:vscode")

# Combined scope modifiers
result = kg.query("relation:calls@session:s1@channel:code")
```

### Scope-Aware Wiki Links

In Joplin notes and documents, scope modifiers can be appended to wiki links:

| Syntax | Meaning |
|--------|---------|
| `[[entity:function:parse@session:impl-session]]` | Entity in specific session |
| `[[entity:function:parse@project:snake-game]]` | Entity in specific project |
| `[[entity:function:parse@channel:vscode]]` | Entity from specific channel |
| `[[entity:function:parse@session:s1@channel:discord]]` | Combined scope |

### Joplin Frontmatter

Joplin notes can include YAML frontmatter for automatic session detection:

```yaml
---
session_id: impl-session
project: snake-game
topic: game-logic
channel: joplin
---
# Note content follows...
```

When frontmatter is present, all entities extracted from the note are automatically assigned the corresponding scope_id and source_channel.

## Memory Update Pattern

When the user provides new information:

1. Check if entity exists: `kg.query("entity:{type}[{name}]")`
2. If exists, update properties
3. If new, create entity and relations
4. Save wiki layer for human readability

## Agent Harness

This project uses a Moon Cell harness for SPEC tracking, model routing, and agent team blueprints.

- Harness source of truth: `.moon-cell/`
- Canonical SPEC index: `.moon-cell/MANIFEST.md`
- Current context: `.moon-cell/docs/harness/CONTEXT_HANDOFF.md`
- Task routing: `.moon-cell/docs/harness/TASK_ROUTING.md`
---
id: SPEC-SESSION-001
version: "1.0.0"
status: completed
created: "2026-04-25"
completed: "2026-04-28"
updated: "2026-04-25"
author: Seung Hyun Myung
priority: high
issue_number: 0
---

# SPEC-SESSION-001: Hierarchical Session Memory & Scope System

## HISTORY

- 2026-04-25: Initial draft created

## Overview

Add session-scoped memory with infinite-depth project-topic-session hierarchy to the Mnemosyne Knowledge Graph. Enables AI agents working across multiple chat/coding sessions to maintain isolated per-session context while sharing knowledge at project and topic levels.

## Scope

### In Scope

- Session, project, and topic entities with parent-child hierarchy
- Scope-based read/write visibility (global > project > topic > session)
- Source channel tracking (discord, teams, slack, code, manual)
- Extended query language with scope, channel, and temporal modifiers
- Cross-session referencing within same project
- Backward-compatible migration for existing data

### Out of Scope

- Joplin plugin session integration (deferred to SPEC-SESSION-002)
- Extraction pipeline session awareness (deferred to SPEC-SESSION-002)
- Schema files for session/project domain (separate task)
- UI for session management in Joplin
- Real-time session synchronization between agents

---

## Requirements

### REQ-001: Scope Entity Hierarchy

**The system shall** support an infinite-depth scope hierarchy using a `scopes` table with self-referencing `parent_id`.

EARS: The knowledge graph **shall** store scope entities (project, topic, session) in a `scopes` SQLite table where each scope has an optional `parent_id` referencing another scope, enabling tree structures of arbitrary depth.

Scope types:
- `project`: Top-level container (parent_id = NULL)
- `topic`: Sub-area within a project (parent_id = project)
- `session`: Individual work context (parent_id = topic or project)

### REQ-002: Entity Scope Assignment

**The system shall** allow entities and relations to be assigned to a scope via a nullable `scope_id` foreign key.

EARS: Each entity and relation **shall** have an optional `scope_id` field referencing the `scopes` table. Entities with `scope_id = NULL` are global (visible to all scopes). Entities with a scope_id are visible to their own scope and all ancestor scopes.

### REQ-003: Source Channel Tracking

**The system shall** track the source channel of each entity and relation.

EARS: Each entity and relation **shall** have a `source_channel` field (TEXT) with values from: `discord`, `teams`, `slack`, `code`, `manual`, `legacy`. The default for existing entities after migration **shall** be `legacy`.

### REQ-004: Scope-based Visibility

**The system shall** enforce scope-based read/write visibility rules.

EARS: The system **shall** implement the following visibility rules:
- **Write**: An entity can only be created/modified within its assigned scope
- **Read**: An entity is visible from its own scope and all descendant scopes
- **Global scope**: Entities with `scope_id = NULL` are visible everywhere

### REQ-005: Extended Query Language

**The system shall** extend the existing query language with scope, channel, and temporal modifiers.

EARS: The query() method **shall** support the following modifiers appended to existing query syntax:
- `@session:name` — Filter to specific session scope
- `@project:name` — Filter to specific project scope
- `@topic:name` — Filter to specific topic scope
- `@channel:source` — Filter by source channel
- `@after:ISO_DATE` — Filter entities created after date
- `@before:ISO_DATE` — Filter entities created before date
- `@siblings` — Include entities from sibling scopes (same parent)

Example: `entity:task[status:active]@project:snake-game@channel:code`

### REQ-006: ScopeManager Class

**The system shall** provide a ScopeManager class for scope CRUD operations.

EARS: The system **shall** provide a `ScopeManager` class (in `core/graph/scope_manager.py`) with methods:
- `create_scope(name, scope_type, parent_id=None)` — Create a new scope
- `get_scope(scope_id)` — Retrieve scope by ID
- `get_scope_by_name(name)` — Retrieve scope by name
- `list_children(scope_id)` — List direct children of a scope
- `get_ancestors(scope_id)` — Get all ancestor scopes (recursive)
- `get_descendants(scope_id)` — Get all descendant scopes (recursive)
- `delete_scope(scope_id)` — Delete scope and reassign or cascade entities
- `get_siblings(scope_id)` — Get scopes sharing the same parent

### REQ-007: Backward Compatibility

**The system shall** maintain full backward compatibility with existing data and queries.

EARS: After migration:
- All existing queries **shall** work without modification
- Existing entities **shall** have `scope_id = NULL` (global scope)
- Existing entities **shall** have `source_channel = 'legacy'`
- The `query()` method **shall** treat unmodified queries as global scope searches
- `add_entity()` and `add_relation()` **shall** accept optional `scope_id` and `source_channel` parameters with sensible defaults

### REQ-008: Database Migration

**The system shall** perform a non-destructive migration adding new tables and columns.

EARS: The `_init_db()` method **shall** detect missing tables/columns and add them without dropping existing data. The migration **shall**:
- Create `scopes` table if not exists
- Add `scope_id` column to `entities` table (TEXT, nullable, default NULL)
- Add `scope_id` column to `relations` table (TEXT, nullable, default NULL)
- Add `source_channel` column to `entities` table (TEXT, default 'legacy')
- Add `source_channel` column to `relations` table (TEXT, default 'legacy')
- Create indexes on new columns

---

## Files to Modify

| File | Change Type | Description |
|------|-------------|-------------|
| `core/graph/knowledge_graph.py` | MODIFY | Entity/Relation dataclass extensions, schema migration, query extensions |
| `core/graph/scope_manager.py` | NEW | ScopeManager class for hierarchy CRUD |
| `core/graph/__init__.py` | MODIFY | Export ScopeManager |
| `core/schema/base.md` | NEW | Base schema for project/topic/session entities |
| `AGENTS.md` | MODIFY | Add session-aware API documentation |
| `CLAUDE.md` | MODIFY | Add session query examples |

## Delta Markers

### [DELTA] core/graph/knowledge_graph.py
- [MODIFY] Entity dataclass — add scope_id, source_channel fields
- [MODIFY] Relation dataclass — add scope_id, source_channel fields
- [MODIFY] _init_db() — add scopes table, new columns, migration logic
- [MODIFY] add_entity() — accept scope_id, source_channel params
- [MODIFY] add_relation() — accept scope_id, source_channel params
- [MODIFY] query() — parse and apply scope/channel/temporal modifiers
- [NEW] _query_scope() — resolve scope visibility for queries

### [NEW] core/graph/scope_manager.py
- [NEW] ScopeManager class with all scope CRUD operations
- [NEW] Recursive CTE queries for ancestor/descendant traversal

### [DELTA] core/schema/base.md
- [NEW] project entity definition
- [NEW] topic entity definition
- [NEW] session entity definition
- [NEW] Base properties (_scope_id, _source_channel)

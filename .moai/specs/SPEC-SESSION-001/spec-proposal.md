# SPEC-SESSION-001: Hierarchical Session Memory Proposal

**Date**: 2026-04-25
**Status**: Proposal — Awaiting Selection
**Research**: `.moai/specs/SPEC-SESSION-001/research.md`

---

## Background

The Mnemosyne Knowledge Graph currently operates as a flat, sessionless graph. All entities share one global namespace with no concept of project boundaries, topic organization, session isolation, or source tracking. The research document (research.md) identifies 5 categories of gaps: missing schema components, database tables, query language extensions, and integration points.

This proposal presents three candidate approaches to deliver hierarchical session memory with project-topic-session tree structure, cross-session referencing, and source channel tracking.

---

## Feature Summary

| Feature | Description |
|---------|-------------|
| Session Memory | Each chat/coding session has isolated memory via session_id |
| Project-Topic-Session Hierarchy | Project -> N Topics -> N Sessions, infinite nesting via parent_id |
| Cross-session Referencing | Sessions can read from sibling sessions within same project |
| Source Channel Tracking | Track whether knowledge came from Discord/Teams/Slack/Code |
| Scope-based Visibility | global > project > topic > session scope for read/write control |

---

## Candidate 1: Comprehensive Single SPEC

**SPEC ID**: SPEC-SESSION-001
**Scope**: All 5 features in one specification
**Estimated files to modify**: 9
**Approach**: Implement the complete session memory system as a single deliverable

### Rationale

All features are tightly coupled. The hierarchy model defines the data structure that the query language must support, and the integration layer depends on both. Delivering everything together ensures no partial or inconsistent states exist in the codebase.

### Risk

Large change surface (9 files, ~600-800 lines of new/modified code). Harder to review incrementally. A single bug in any layer blocks the entire feature.

### EARS Requirements

#### Data Model

**REQ-SESSION-001**: The system SHALL maintain a `scopes` table with columns `id` (TEXT PK), `parent_id` (TEXT, nullable, self-referencing FK), `scope_type` (TEXT: 'project'|'topic'|'session'), `name` (TEXT), `metadata` (TEXT, JSON), `source_channel` (TEXT), `created_at` (TEXT), and enforce via CHECK constraint that parent_id references a scope of a higher or equal tier.

**REQ-SESSION-002**: Each entity SHALL have an optional `scope_id` column (TEXT, nullable, FK to scopes.id), where NULL denotes global scope visible to all sessions.

**REQ-SESSION-003**: Each entity SHALL have a `source_channel` column (TEXT, not null, default 'unknown') identifying the origin platform, with allowed values: 'discord', 'teams', 'slack', 'code', 'note', 'manual', 'import', 'unknown'.

**REQ-SESSION-004**: Each relation SHALL have an optional `scope_id` column (TEXT, nullable, FK to scopes.id) inheriting the scope of its source entity when not explicitly provided.

#### Scope Visibility

**REQ-SESSION-005**: When a query specifies a session scope, the system SHALL return entities from: (a) the session itself, (b) its parent topic, (c) its parent project, (d) global scope (scope_id IS NULL). This is the ascending visibility chain.

**REQ-SESSION-006**: A session SHALL be able to read entities from sibling sessions (sessions sharing the same parent topic) when explicitly requested via a `@siblings` query modifier.

**REQ-SESSION-007**: Write operations to a scope SHALL be restricted to that scope only. A session SHALL NOT write entities into a parent topic or project scope unless explicitly operating at that scope level.

#### Query Language

**REQ-SESSION-008**: The query language SHALL support scope filter modifiers using the syntax `query@scope_type:scope_name`, where scope_type is one of 'session', 'topic', 'project'.

**REQ-SESSION-009**: The query language SHALL support channel filter modifiers using the syntax `query@channel:channel_name`.

**REQ-SESSION-010**: The query language SHALL support temporal filter modifiers using the syntax `query@after:ISO_DATE` and `query@before:ISO_DATE`.

**REQ-SESSION-011**: Queries without scope or channel modifiers SHALL return results from all scopes, maintaining backward compatibility with the existing query language.

#### Migration

**REQ-SESSION-012**: When the database is opened and the `scopes` table does not exist, the system SHALL create all new tables and columns without data loss. Existing entities SHALL have scope_id = NULL (global) and source_channel = 'legacy'.

#### Integration

**REQ-SESSION-013**: The Joplin plugin SHALL detect session context from note metadata fields (frontmatter or header patterns) and assign extracted entities to the matching scope.

**REQ-SESSION-014**: The extraction pipeline SHALL accept optional parameters: scope_id, source_channel, and propagate these to all created entities and relations.

### Implementation Plan

#### Phase 1: Data Model (core/graph/knowledge_graph.py)

1. Add `Scope` dataclass with fields: id, parent_id, scope_type, name, metadata, source_channel, created_at
2. Extend `Entity` dataclass: add scope_id (Optional[str]), source_channel (str)
3. Extend `Relation` dataclass: add scope_id (Optional[str])
4. Add `_init_session_schema()` method to create scopes table and new columns
5. Add migration logic: ALTER TABLE for existing databases (scope_id, source_channel columns)
6. Add indexes: idx_entities_scope, idx_entities_channel, idx_scopes_parent, idx_scopes_type

#### Phase 2: Scope Manager (new: core/graph/scope_manager.py)

1. `ScopeManager` class with methods:
   - `create_scope(scope_type, name, parent_id=None, source_channel='unknown') -> Scope`
   - `get_scope(scope_id) -> Optional[Scope]`
   - `get_ancestors(scope_id) -> List[Scope]` (ascending chain to root)
   - `get_siblings(scope_id) -> List[Scope]` (same parent)
   - `get_descendants(scope_id) -> List[Scope]` (all children recursively)
   - `resolve_visible_scope_ids(scope_id) -> List[str]` (IDs visible from a scope)
   - `delete_scope(scope_id, cascade=False)` (delete with optional cascade)

#### Phase 3: Query Extensions (core/graph/knowledge_graph.py)

1. Add `_query_with_context()` method to parse @-modifiers
2. Extend `_query_entity()` to filter by scope_id IN (visible scopes) and source_channel
3. Extend `_query_relation()` similarly
4. Extend `_query_search()` with scope and channel filters
5. Add `_query_scope()` for hierarchy queries: `scope:project_name` returns all scopes in project
6. Add `_query_temporal()` for time-range filtered queries

#### Phase 4: Integration (Joplin + Extraction)

1. Extend Joplin plugin `detectDomain()` to also detect session context
2. Add `extractSessionMetadata()` method to Joplin plugin
3. Extend `extractBasedOnDomain()` to accept and apply scope_id/source_channel
4. Add scope_id and source_channel parameters to `TreeSitterExtractor` and `SemanticExtractor`
5. Update wiki link syntax to support `[[entity:type:name@session]]`

#### Phase 5: CLI & Documentation

1. Extend CLI arguments: `--scope`, `--channel`, `--session`
2. Update CLAUDE.md with session query examples
3. Update AGENTS.md with session-aware patterns

### Files to Modify

| File | Change Type | Description |
|------|-------------|-------------|
| `core/graph/knowledge_graph.py` | Modify | Entity/Relation dataclass extension, schema migration, query extensions |
| `core/graph/scope_manager.py` | **New** | ScopeManager class for hierarchy CRUD and visibility resolution |
| `core/graph/__init__.py` | Modify | Export ScopeManager |
| `core/extraction/deterministic/code_parser.py` | Modify | Add scope_id/source_channel params to extraction methods |
| `core/extraction/semantic/slm_extractor.py` | Modify | Add scope_id/source_channel params to extraction methods |
| `joplin-plugin/knowledge-graph/src/index.ts` | Modify | Session context detection, scope-aware extraction |
| `AGENTS.md` | Modify | Session-aware usage patterns |
| `CLAUDE.md` | Modify | Session query examples in usage section |
| `requirements.txt` | Modify (if needed) | No new dependencies expected |

### Acceptance Criteria

1. **AC-001**: Creating a project scope, topic scope within it, and session scope within the topic succeeds, and `get_ancestors(session_id)` returns [topic, project]
2. **AC-002**: Adding entities to a session scope and querying from that session returns those entities plus entities from parent topic, parent project, and global scope
3. **AC-003**: Querying with `@channel:discord` returns only entities where source_channel = 'discord'
4. **AC-004**: Existing database opened without migration continues to work; existing entities are queryable with scope_id=NULL and source_channel='legacy'
5. **AC-005**: Query `entity:function[authenticate]@session:my-session` returns the entity only if it exists within the session's visible scope chain
6. **AC-006**: `scope:my-project` returns the project scope, its topics, and all sessions within those topics
7. **AC-007**: Sibling session read via `@siblings` modifier returns entities from sessions sharing the same parent topic
8. **AC-008**: Joplin plugin extracts entities with correct scope_id when note contains session metadata
9. **AC-009**: All existing tests pass without modification (backward compatibility)
10. **AC-010**: New test coverage >= 85% for all new code (scope_manager.py, query extensions)

---

## Candidate 2: Incremental 3-SPEC Approach

**SPEC IDs**: SPEC-SESSION-001A, SPEC-SESSION-001B, SPEC-SESSION-001C
**Scope**: Features split across 3 dependent SPECs
**Approach**: Data model first, then query language, then integration

### Rationale

Each SPEC has a clear completion boundary and can be reviewed, tested, and merged independently. If any phase encounters issues, earlier phases are still valuable. The data model is the foundation — once it exists, query language and integration can proceed in parallel if needed.

### SPEC-SESSION-001A: Session Hierarchy Data Model

**Dependencies**: None (foundational)
**Files**: 3 (knowledge_graph.py, scope_manager.py, __init__.py)

#### EARS Requirements

**REQ-001A-001**: The system SHALL maintain a `scopes` table as described in Candidate 1 REQ-SESSION-001.

**REQ-001A-002**: Entity and Relation dataclasses SHALL be extended with scope_id and source_channel as described in REQ-SESSION-002 and REQ-SESSION-003.

**REQ-001A-003**: A `ScopeManager` class SHALL provide CRUD operations for scope containers: create, get, get_ancestors, get_siblings, get_descendants, resolve_visible_scope_ids, delete.

**REQ-001A-004**: Database migration SHALL be backward compatible per REQ-SESSION-012.

**REQ-001A-005**: The system SHALL enforce that scope_type follows a valid parent-child ordering: project -> topic -> session. A session's parent MUST be a topic or session. A topic's parent MUST be a project. A project's parent MUST be NULL.

#### Acceptance Criteria

1. ScopeManager.create_scope creates a project, then topic within it, then session within topic, and each can be retrieved
2. get_ancestors(session_id) returns [topic_scope, project_scope] in order
3. resolve_visible_scope_ids(session_id) returns [session_id, topic_id, project_id] plus NULL for global
4. Existing database migration preserves all data; existing entities have scope_id=NULL, source_channel='legacy'
5. All existing tests pass without modification

#### Implementation Plan

1. Add Scope dataclass to knowledge_graph.py
2. Extend Entity/Relation dataclasses
3. Add _init_session_schema() to KnowledgeGraph._init_db()
4. Create core/graph/scope_manager.py with ScopeManager class
5. Add migration path for existing databases
6. Write tests for ScopeManager (CRUD, hierarchy, visibility)

### SPEC-SESSION-001B: Session-Aware Query Language

**Dependencies**: SPEC-SESSION-001A (data model)
**Files**: 2 (knowledge_graph.py query methods, AGENTS.md)

#### EARS Requirements

**REQ-001B-001**: The query method SHALL parse @-modifiers for scope, channel, and temporal filters per REQ-SESSION-008 through REQ-SESSION-010.

**REQ-001B-002**: When a scope filter is present, the query SHALL use ScopeManager.resolve_visible_scope_ids() to determine the set of visible scope_ids and filter results accordingly.

**REQ-001B-003**: Queries without @-modifiers SHALL behave identically to the current implementation (backward compatible) per REQ-SESSION-011.

**REQ-001B-004**: The system SHALL support a `scope:` query type that returns hierarchy information: `scope:project_name` returns the project and all descendant scopes.

**REQ-001B-005**: The `@siblings` modifier SHALL expand the visible scope set to include all sibling sessions (sessions with the same parent scope).

#### Acceptance Criteria

1. `entity:function[authenticate]@session:my-session` returns only entities visible from that session
2. `entity:task[*]@channel:discord` returns only tasks from Discord
3. `entity:person[*]@after:2026-01-01` returns only persons created after the date
4. `entity:function[*]` (no modifier) returns all functions across all scopes (backward compatible)
5. `scope:my-project` returns project, topics, and sessions as a tree structure
6. `entity:note[*]@session:s1@siblings` returns notes from s1 plus all sibling sessions

### SPEC-SESSION-001C: Integration Layer

**Dependencies**: SPEC-SESSION-001A (data model), SPEC-SESSION-001B (query language)
**Files**: 4 (index.ts, code_parser.py, slm_extractor.py, CLAUDE.md)

#### EARS Requirements

**REQ-001C-001**: The Joplin plugin SHALL detect session metadata from note frontmatter or header patterns and create or match a corresponding scope per REQ-SESSION-013.

**REQ-001C-002**: The extraction pipeline SHALL accept optional scope_id and source_channel parameters per REQ-SESSION-014.

**REQ-001C-003**: The wiki link syntax SHALL be extended to support `[[entity:type:name@scope_type:scope_name]]` for scope-specific entity linking.

**REQ-001C-004**: The CLI SHALL support `--scope`, `--channel`, and `--create-session` arguments for session-aware operations.

#### Acceptance Criteria

1. Joplin plugin correctly assigns scope_id to extracted entities when note has session metadata
2. TreeSitterExtractor with scope_id and source_channel creates entities with correct scope assignment
3. Wiki link `[[entity:function:parse_config@session:my-session]]` renders correctly in Joplin
4. CLI `python -m core.graph.knowledge_graph --query "entity:function[*]" --session my-session` returns scoped results
5. All existing Joplin plugin functionality works without session metadata (backward compatible)

---

## Candidate 3: Minimal 2-SPEC Approach

**SPEC IDs**: SPEC-SESSION-001, SPEC-SESSION-002
**Scope**: Core functionality in SPEC-001, integration in SPEC-002
**Approach**: Data model + query language combined, integration separate

### Rationale

The data model and query language are so tightly coupled that separating them creates an awkward intermediate state where scopes exist but cannot be queried. Combining them into one SPEC delivers a usable core system. Integration with Joplin and extraction pipeline is a natural second step that can be parallelized or deferred.

### SPEC-SESSION-001: Session Hierarchy & Query Engine

**Dependencies**: None
**Files**: 4 (knowledge_graph.py, scope_manager.py, __init__.py, AGENTS.md)

#### EARS Requirements

Combines all requirements from Candidate 2's SPEC-001A and SPEC-001B:
- REQ-001A-001 through REQ-001A-005 (data model)
- REQ-001B-001 through REQ-001B-005 (query language)

#### Additional Requirements

**REQ-SESSION-015**: The KnowledgeGraph class SHALL expose a `create_scope()` convenience method that delegates to ScopeManager, maintaining the single-class API surface pattern used by existing add_entity/add_relation methods.

**REQ-SESSION-016**: The KnowledgeGraph stats method SHALL include scope statistics: count of projects, topics, sessions, and entity distribution across scopes.

#### Acceptance Criteria

Combines acceptance criteria from SPEC-001A and SPEC-001B, plus:
1. `kg.create_scope('project', 'my-project')` creates and returns a scope
2. `kg.get_stats()` includes scope distribution data
3. NetworkX graph construction includes scope_id in node attributes

#### Implementation Plan

Combined from SPEC-001A and SPEC-001B phases, executed sequentially.

### SPEC-SESSION-002: Session Integration Layer

**Dependencies**: SPEC-SESSION-001
**Files**: 5 (index.ts, code_parser.py, slm_extractor.py, CLAUDE.md, content_script.ts)

Same requirements and acceptance criteria as Candidate 2's SPEC-SESSION-001C.

---

## Comparative Analysis

| Dimension | Candidate 1 (Single) | Candidate 2 (3-SPEC) | Candidate 3 (2-SPEC) |
|-----------|----------------------|----------------------|----------------------|
| SPECs produced | 1 | 3 | 2 |
| Files per SPEC | 9 | 3/2/4 | 4/5 |
| Review granularity | Coarse | Fine | Moderate |
| Dependency chain | None | 001A -> 001B -> 001C | 001 -> 002 |
| Partial value | None until complete | 001A is independently useful | 001 is independently usable |
| Review rounds | 1 | 3 | 2 |
| Risk of inconsistency | Low (all at once) | Medium (inter-SPEC gaps) | Low |
| Parallel implementation | Not possible | 001B and 001C could parallelize after 001A | 002 can be parallelized |
| Intermediate states | None (all-or-nothing) | Data model only, then query only | Full core, integration later |

## Recommendation

**Candidate 3 (2-SPEC Approach)** is recommended because:

1. SPEC-SESSION-001 delivers a fully functional core system. After implementation, developers can use session memory via Python API and CLI even without Joplin integration.
2. The intermediate state after SPEC-SESSION-001 is useful, not awkward (unlike Candidate 2's SPEC-001A which creates scopes that cannot be queried).
3. SPEC-SESSION-002 can be deferred or parallelized without blocking core functionality.
4. Two review rounds is manageable while still providing meaningful separation of concerns.
5. The combined data-model + query SPEC avoids the risk of data/query interface mismatch that Candidate 2's split introduces.

---

## Technical Constraints (All Candidates)

1. **SQLite Recursive CTE**: Scope ancestor/descendant queries require WITH RECURSIVE. SQLite has supported this since 3.8.3 (2014). No version concern.
2. **No New Dependencies**: All features are implementable with standard library + existing dependencies (sqlite3, networkx, uuid).
3. **Thread Safety**: KnowledgeGraph uses `check_same_thread=False`. ScopeManager must follow the same pattern or use the same connection.
4. **Database Size**: Each scope adds one row to the scopes table. With typical usage (10 projects x 5 topics x 20 sessions = 1000 scopes), negligible storage impact.
5. **Query Performance**: Scope filtering adds one JOIN per query. With proper indexes on entities.scope_id and scopes.parent_id, performance impact is <5ms per query.
6. **NetworkX Sync**: The in-memory NetworkX graph must include scope_id in node attributes for graph analysis to remain consistent.

---

## Scope Table Schema (All Candidates)

```sql
CREATE TABLE IF NOT EXISTS scopes (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    scope_type TEXT NOT NULL CHECK(scope_type IN ('project', 'topic', 'session')),
    name TEXT NOT NULL,
    metadata TEXT,  -- JSON
    source_channel TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES scopes(id)
);

CREATE INDEX IF NOT EXISTS idx_scopes_parent ON scopes(parent_id);
CREATE INDEX IF NOT EXISTS idx_scopes_type ON scopes(scope_type);
CREATE INDEX IF NOT EXISTS idx_scopes_name ON scopes(name);
```

## Entity/Relation Column Extensions (All Candidates)

```sql
-- Added to entities table
ALTER TABLE entities ADD COLUMN scope_id TEXT REFERENCES scopes(id);
ALTER TABLE entities ADD COLUMN source_channel TEXT NOT NULL DEFAULT 'legacy';

-- Added to relations table
ALTER TABLE relations ADD COLUMN scope_id TEXT REFERENCES scopes(id);

-- New indexes
CREATE INDEX IF NOT EXISTS idx_entities_scope ON entities(scope_id);
CREATE INDEX IF NOT EXISTS idx_entities_channel ON entities(source_channel);
CREATE INDEX IF NOT EXISTS idx_relations_scope ON relations(scope_id);
```

## ScopeManager API (All Candidates)

```python
class ScopeManager:
    def __init__(self, conn: sqlite3.Connection): ...

    def create_scope(self, scope_type: str, name: str,
                     parent_id: Optional[str] = None,
                     source_channel: str = 'unknown',
                     metadata: Optional[Dict] = None) -> Scope: ...

    def get_scope(self, scope_id: str) -> Optional[Scope]: ...

    def get_ancestors(self, scope_id: str) -> List[Scope]: ...

    def get_children(self, scope_id: str) -> List[Scope]: ...

    def get_siblings(self, scope_id: str) -> List[Scope]: ...

    def get_descendants(self, scope_id: str) -> List[Scope]: ...

    def resolve_visible_scope_ids(self, scope_id: str) -> List[Optional[str]]: ...

    def find_scope_by_name(self, name: str, scope_type: Optional[str] = None) -> Optional[Scope]: ...

    def delete_scope(self, scope_id: str, cascade: bool = False) -> bool: ...
```

## Query Syntax Extension (All Candidates)

| Query | Behavior |
|-------|----------|
| `entity:function[parse]` | All scopes (backward compatible) |
| `entity:function[parse]@session:s1` | Entities visible from session s1 |
| `entity:function[parse]@project:p1` | Entities in project p1 scope only |
| `entity:task[*]@channel:discord` | All tasks from Discord |
| `entity:person[*]@after:2026-01-01` | Persons created after date |
| `entity:note[*]@session:s1@siblings` | Notes from s1 plus sibling sessions |
| `scope:my-project` | Hierarchy tree for project |
| `scope:my-project/stats` | Entity distribution by scope within project |

---

## Decision Required

Select one of the three candidates. The selected candidate will be expanded into formal spec.md, plan.md, and acceptance.md documents.

**Recommended**: Candidate 3 (2-SPEC approach).

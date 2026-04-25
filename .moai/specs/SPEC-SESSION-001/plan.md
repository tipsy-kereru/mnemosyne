# Implementation Plan: SPEC-SESSION-001

## Approach

Incremental extension of the existing KnowledgeGraph class with a new ScopeManager module. All changes maintain backward compatibility.

## Task Breakdown

### Task 1: Scope Dataclass & Database Migration
**File**: `core/graph/knowledge_graph.py`
**What**:
- Add `Scope` dataclass (id, parent_id, scope_type, name, metadata, source_channel, created_at)
- Extend `Entity` with `scope_id: Optional[str] = None` and `source_channel: str = 'legacy'`
- Extend `Relation` with `scope_id: Optional[str] = None`
- Add `_init_session_schema()` method: create `scopes` table, ALTER entities/relations for new columns
- Add indexes: idx_entities_scope, idx_entities_channel, idx_relations_scope, idx_scopes_parent, idx_scopes_type
- Migration must be idempotent (PRAGMA table_info to detect missing columns)
- Update `add_entity()` and `add_relation()` to accept optional `scope_id`, `source_channel`
- Update `_build_networkx()` to include scope_id in node attributes
- Update `get_stats()` to include scope distribution

### Task 2: ScopeManager Class
**File**: `core/graph/scope_manager.py` (NEW)
**What**:
- `ScopeManager.__init__(self, conn)` — takes shared sqlite3.Connection
- `create_scope(scope_type, name, parent_id, source_channel, metadata)` — with type validation (project parent=NULL, topic parent=project, session parent=topic/session)
- `get_scope(scope_id)` — single scope retrieval
- `get_ancestors(scope_id)` — recursive CTE up the tree
- `get_children(scope_id)` — direct children
- `get_siblings(scope_id)` — same parent, excluding self
- `get_descendants(scope_id)` — recursive CTE down the tree
- `find_scope_by_name(name, scope_type)` — lookup by name
- `delete_scope(scope_id, cascade)` — delete with optional entity cascade
- `resolve_visible_scope_ids(scope_id)` — returns [self_id, ...ancestor_ids, None] (None = global)

### Task 3: Extended Query Language
**File**: `core/graph/knowledge_graph.py`
**What**:
- Parse `@` modifiers in `query()`: `@session:name`, `@project:name`, `@topic:name`, `@channel:src`, `@after:ISO`, `@before:ISO`, `@siblings`
- Use ScopeManager.resolve_visible_scope_ids() for scope filtering
- Add `scope:name` query type returning hierarchy tree
- Apply filters in `_query_entity()`, `_query_relation()`, `_query_search()`
- Backward compat: queries without `@` return all scopes (unchanged behavior)

### Task 4: KnowledgeGraph Convenience Methods
**File**: `core/graph/knowledge_graph.py`
**What**:
- Add `create_scope()` delegate method on KnowledgeGraph
- Add `get_scope()` delegate method
- Wire ScopeManager instance in `__init__`
- Update `__init__.py` to export ScopeManager and Scope

### Task 5: Base Schema File
**File**: `core/schema/base.md` (NEW)
**What**:
- Define project, topic, session entity types
- Define _base_properties (scope_id, source_channel)
- Document scope visibility rules

### Task 6: Tests
**File**: `tests/test_scope_manager.py` (NEW), `tests/test_knowledge_graph_session.py` (NEW)
**What**:
- ScopeManager CRUD tests (create, get, ancestors, children, siblings, descendants)
- Scope hierarchy validation (project→topic→session ordering)
- Scope visibility resolution tests
- Entity creation with scope_id and source_channel
- Query with scope/channel/temporal modifiers
- Backward compatibility: existing queries work unchanged
- Database migration: existing data preserved
- Edge cases: circular parent refs, orphan scopes, empty queries

## Dependency Order

```
Task 1 (Schema + Migration) ←── Task 2 (ScopeManager) ←── Task 3 (Query Extensions)
                                                             ←── Task 4 (Convenience Methods)
Task 1 ←── Task 5 (Schema File)
Task 2 ←── Task 6 (Tests)
```

Tasks 4, 5 can run after Task 1 independently. Task 3 depends on Task 2. Task 6 depends on Task 2.

## Acceptance Criteria (from SPEC)

1. Creating project→topic→session hierarchy succeeds; get_ancestors returns correct chain
2. Entities in session scope visible from session + all ancestor scopes + global
3. `@channel:discord` filters correctly
4. Existing database migration preserves all data
5. `@session:name` scope filtering works
6. `scope:project-name` returns hierarchy tree
7. `@siblings` includes sibling session entities
8. All existing queries work without modification
9. Test coverage >= 85% for new code

## Technical Constraints

- SQLite recursive CTE for ancestor/descendant queries (supported since 3.8.3)
- No new external dependencies
- Thread safety: use shared connection with `check_same_thread=False`
- NetworkX sync: include scope_id in node attributes

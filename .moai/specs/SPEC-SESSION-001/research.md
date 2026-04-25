# SPEC-SESSION-001: Session Memory & Hierarchy Research

**Date**: 2026-04-25  
**Project**: Mnemosyne Knowledge Graph  
**Domain**: Session Memory Architecture  
**Status**: Deep Research Complete

---

## Executive Summary

This research document provides a comprehensive analysis of the current Mnemosyne Knowledge Graph architecture and identifies gaps for implementing session memory, project-topic-session hierarchy, cross-session referencing, and source channel tracking. The analysis focuses on understanding the existing Entity/Relation schema, SQLite database structure, query capabilities, and integration points for session-based functionality.

---

## 1. Architecture Analysis

### 1.1 Current System Architecture

The Mnemosyne Knowledge Graph follows a 4-layer architecture:

```
Raw Source Layer (Immutable)
       ↓
Wiki Layer (Markdown + [[wiki-links]])
       ↓
Schema Layer (CLAUDE.md / AGENTS.md)
       ↓
Knowledge Graph (SQLite + NetworkX)
```

**Key Components**:
- **core/graph/knowledge_graph.py**: Main graph database (lines 39-443)
- **core/schema/**: Domain-specific schemas (daily-life.md, coding.md, legal.md)
- **core/extraction/**: Deterministic and semantic extraction pipelines
- **joplin-plugin/knowledge-graph/src/index.ts**: Joplin integration plugin

### 1.2 Current Data Flow

1. **Raw sources** → **Deterministic extraction** → **Wiki layer** → **Graph database**
2. **Query patterns**: `entity:type[name]`, `relation:type`, `path:source,target`, `search:term`
3. **Integration**: Joplin plugin provides wiki-link support and entity extraction

---

## 2. Current Entity/Relation Schema Analysis

### 2.1 Entity Dataclass (`core/graph/knowledge_graph.py`, lines 15-25)

```python
@dataclass
class Entity:
    id: str                    # Unique identifier
    type: str                  # Entity type (function, task, person, etc.)
    name: str                  # Human-readable name
    properties: Dict[str, Any] # Flexible properties dict
    created_at: str            # ISO timestamp
    updated_at: str            # ISO timestamp
    version: int = 1           # Version for change tracking
```

### 2.2 Relation Dataclass (`core/graph/knowledge_graph.py`, lines 27-37)

```python
@dataclass
class Relation:
    id: str                    # Unique identifier
    source_id: str            # Source entity ID
    target_id: str            # Target entity ID
    relation_type: str        # Relation type (calls, assigned_to, etc.)
    properties: Dict[str, Any] # Flexible properties
    created_at: str            # ISO timestamp
    version: int = 1           # Version tracking
```

### 2.3 Domain-Specific Entity Types

**Daily Life Domain** (daily-life.md, lines 4-67):
- `task`: Action items with deadline, priority, status
- `person`: Contacts with relationship history
- `place`: Physical/virtual locations
- `event`: Calendar events and appointments
- `habit`: Recurring behavior patterns
- `preference`: User preferences with confidence
- `note`: General reference notes

**Coding Domain** (coding.md, lines 4-87):
- `function`: Functions/methods with signature, language, complexity
- `class`: Classes/structs with methods and attributes
- `module`: Packages, namespaces, crates
- `api`: API endpoints (REST, GraphQL, gRPC)
- `bug`: Bug reports with severity and affected functions
- `feature`: Feature requests with implementation tracking
- `test`: Test cases with coverage information
- `dependency`: External libraries with version tracking

**Legal Domain** (legal.md, lines 4-78):
- `statute`: Laws with jurisdiction and code citations
- `clause`: Document sections with obligation types
- `case`: Court cases with holdings and reasoning
- `party`: Legal entities (individuals, corporations)
- `obligation`: Legal duties and requirements
- `deadline`: Time limits for filings, responses, payments
- `contract`: Legal agreements with clauses and status

### 2.4 Current Relationship Types

**Daily Life Relations** (daily-life.md, lines 70-86):
- `task.assigned_to: person`
- `task.located_at: place`
- `task.part_of: project`
- `person.interacts_with: person`
- `person.knows_via: event`
- `person.mentioned_in: note`
- `event.followed_by: event`
- `habit.supports: goal`
- `task.blocks: task`

**Coding Relations** (coding.md, lines 91-113):
- `function.imports: module`
- `function.calls: function`
- `function.defined_in: class | module`
- `function.tested_by: test`
- `function.caught_by: bug`
- `class.contains: function`
- `class.imports: module`
- `class.inherits: class`
- `module.exports: function | class | api`
- `module.imports: module`
- `bug.affected: function | class`
- `bug.resolved_by: commit`
- `feature.implements: api | function`
- `feature.requires: dependency`
- `test.covers: function | class | api`
- `test.triggers: bug`

**Legal Relations** (legal.md, lines 82-103):
- `clause.derived_from: statute`
- `clause.引用: statute` (references)
- `clause.creates: obligation`
- `case.applies: statute`
- `case.cites: case`
- `case.involves: party`
- `obligation.arises_from: clause | statute`
- `obligation.benefits: party`
- `deadline.for_case: case`
- `deadline.for_contract: contract`
- `contract.between: party`
- `contract.contains: clause`
- `contract.amended_by: contract`
- `party.represented_by: party` (counsel)
- `party.against: party` (litigation)

---

## 3. Current SQLite Database Schema

### 3.1 Main Tables (`core/graph/knowledge_graph.py`, lines 57-110)

```sql
-- Entities table
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    properties TEXT,      -- JSON
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER DEFAULT 1
);

-- Relations table
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    properties TEXT,      -- JSON
    created_at TEXT NOT NULL,
    version INTEGER DEFAULT 1,
    FOREIGN KEY (source_id) REFERENCES entities(id),
    FOREIGN KEY (target_id) REFERENCES entities(id)
);

-- Entity history for temporal tracking
CREATE TABLE IF NOT EXISTS entity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    properties TEXT,
    changed_at TEXT NOT NULL,
    change_type TEXT NOT NULL,  -- created, updated, deleted
    version INTEGER
);
```

### 3.2 Current Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)
CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(relation_type)
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id)
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id)
```

### 3.3 Temporal Tracking

The system includes basic temporal tracking via `entity_history` table (lines 90-101) that records:
- Entity changes (created, updated, deleted)
- Version tracking
- Timestamps for each change

---

## 4. Current Query Language Capabilities

### 4.1 Query Types (`core/graph/knowledge_graph.py`, lines 241-394)

**Entity Queries**: `entity:type[name]`
- Exact match: `entity:function[authenticate]`
- Pattern match: `entity:function[*auth*]`
- Type filter: `entity:function`

**Relation Queries**: `relation:type(source_id, target_id)`
- All relations: `relation:calls`
- Specific relation: `relation:calls(function_a, function_b)`

**Path Queries**: `path:source_name, target_name`
- Finds shortest path between entities
- Returns path and edge information

**Search Queries**: `search:term`
- Fuzzy search on entity names and properties
- Uses SQL LIKE with % wildcards

### 4.2 Query Limitations

1. **No session-aware queries**: Cannot query within specific sessions
2. **No hierarchy support**: Cannot query project → topic → session structure
3. **No temporal filtering**: Cannot query entities from specific time ranges
4. **No channel tracking**: Cannot filter by source channel (Discord, Slack, etc.)
5. **No cross-session referencing**: Cannot link entities across sessions

---

## 5. Gaps for Session/Hierarchy Support

### 5.1 Missing Schema Components

**Session Hierarchy Fields**:
- `session_id`: Unique session identifier
- `project_id`: Project identifier
- `topic_id`: Topic within project
- `source_channel`: Source platform (discord, slack, teams, etc.)
- `session_timestamp`: Session start/end times
- `session_metadata`: Additional session context

**Cross-Session Reference Fields**:
- `reference_id`: For linking related entities across sessions
- `continuation_id`: For continuing conversations across sessions
- `context_id`: For maintaining conversation context

### 5.2 Database Schema Gaps

1. **No session management tables**
2. **No hierarchy tracking tables**
3. **No source channel tracking**
4. **No cross-session reference tables**
5. **Limited temporal filtering capabilities**

### 5.3 Query Language Gaps

1. **No session-aware query syntax**
2. **No hierarchy traversal queries**
3. **No temporal range queries**
4. **No channel filtering in queries**
5. **No cross-session reference queries**

### 5.4 Integration Gaps

1. **Joplin plugin** (`joplin-plugin/knowledge-graph/src/index.ts`, lines 346-401):
   - `detectDomain()`: Only detects daily/coding/legal domains
   - `extractBasedOnDomain()`: No session-aware extraction
   - No session metadata extraction

2. **Extraction pipeline**: No session context awareness
3. **Wiki layer**: No session-specific organization

---

## 6. Recommended Implementation Approach

### 6.1 Schema Extension Strategy

#### 6.1.1 Entity Schema Extension

```python
@dataclass
class Entity:
    # Existing fields...
    session_id: str          # New: Session identifier
    project_id: str          # New: Project identifier  
    topic_id: str           # New: Topic within project
    source_channel: str     # New: Source platform
    reference_id: str       # New: Cross-session reference
    session_metadata: Dict[str, Any]  # New: Session context
```

#### 6.1.2 New Database Tables

```sql
-- Sessions table
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    topic_id TEXT,
    source_channel TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    metadata TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- Projects table
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);

-- Cross-session references table
CREATE TABLE IF NOT EXISTS cross_session_references (
    id TEXT PRIMARY KEY,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    reference_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_entity_id) REFERENCES entities(id),
    FOREIGN KEY (target_entity_id) REFERENCES entities(id)
);
```

### 6.2 Query Language Extension

#### 6.2.1 New Query Types

**Session-aware queries**:
- `entity:type[name]@session_id`
- `relation:type@session_id`
- `path:source,target@session_id`

**Hierarchy queries**:
- `entity:type[name]@project:topic`
- `relation:type@project:topic`
- `session:project_id`

**Temporal queries**:
- `entity:type[name]@after:2024-01-01`
- `entity:type[name]@before:2024-12-31`
- `entity:type[name]@range:2024-01-01,2024-12-31`

**Channel queries**:
- `entity:type[name]@channel:discord`
- `relation:type@channel:slack`

#### 6.2.2 Extended Query Implementation

```python
def query(self, query_str: str) -> Dict[str, Any]:
    # Parse new query syntax with session/hierarchy filters
    if '@' in query_str:
        return self._query_with_context(query_str)
    return self._query_original(query_str)
```

### 6.3 Integration Strategy

#### 6.3.1 Joplin Plugin Enhancement

**Enhanced domain detection** (`joplin-plugin/knowledge-graph/src/index.ts`, lines 346-361):
- Add session context detection
- Add channel identification
- Add project/topic metadata extraction

**Session-aware extraction** (`joplin-plugin/knowledge-graph/src/index.ts`, lines 364-401):
- Extract session metadata from note content
- Link entities to specific sessions
- Maintain cross-session references

#### 6.3.2 Extraction Pipeline Enhancement

**Session context extraction**:
- Extract session identifiers from note headers
- Detect project/topic from context
- Identify source channels from metadata
- Maintain conversation continuity

---

## 7. Files That Need Modification

### 7.1 Core Graph Database (`core/graph/knowledge_graph.py`)

**Lines 15-25**: Entity dataclass extension
- Add session_id, project_id, topic_id, source_channel, reference_id, session_metadata

**Lines 27-37**: Relation dataclass extension  
- Add session_id, project_id, topic_id, source_channel

**Lines 57-110**: Database schema modification
- Add sessions table
- Add projects table
- Add cross_session_references table
- Modify existing table schemas

**Lines 138-207**: Entity/Relation creation methods
- Add session context parameters
- Update SQL insert statements

**Lines 241-394**: Query methods
- Add context-aware query parsing
- Add temporal filtering
- Add channel filtering
- Add hierarchy queries

**Lines 402-419**: Entity history method
- Add temporal range filtering
- Add session-aware history queries

### 7.2 Domain Schema Files

**core/schema/daily-life.md**: Add session-aware entity definitions
**core/schema/coding.md**: Add session-aware entity definitions
**core/schema/legal.md**: Add session-aware entity definitions

### 7.3 Extraction Pipeline

**core/extraction/deterministic/code_parser.py**: 
- Add session context extraction
- Add project/topic metadata

**core/extraction/semantic/slm_extractor.py**:
- Add session context awareness
- Add cross-session reference detection

### 7.4 Joplin Plugin

**joplin-plugin/knowledge-graph/src/index.ts**:
- Lines 346-361: Enhanced domain detection with session context
- Lines 364-401: Session-aware extraction
- Add session management methods
- Add cross-session reference handling

### 7.5 Documentation

**AGENTS.md**: Update memory update pattern with session support
**CLAUDE.md**: Update usage examples with session queries

---

## 8. Risks and Constraints

### 8.1 Technical Risks

1. **Database Migration Complexity**: Adding session fields may require data migration
2. **Query Performance**: Hierarchical queries may impact performance on large graphs
3. **Memory Usage**: Session metadata may increase memory footprint
4. **Backward Compatibility**: Changes may break existing integrations

### 8.2 Data Consistency Risks

1. **Session Identifier Collisions**: Need unique session identifiers across sources
2. **Cross-Session Reference Integrity**: Need to maintain referential integrity
3. **Temporal Data Consistency**: Need proper timestamp handling across sessions

### 8.3 Integration Risks

1. **Joplin Plugin Compatibility**: Changes may break existing Joplin integration
2. **Extraction Pipeline Robustness**: Session extraction may fail on malformed data
3. **Wiki Link Compatibility**: New syntax may break existing wiki links

### 8.4 Performance Constraints

1. **Index Management**: Need proper indexes for session, project, topic queries
2. **Query Optimization**: Complex hierarchy queries need optimization
3. **Storage Efficiency**: Session metadata should be compact and efficient

### 8.5 User Experience Constraints

1. **Query Complexity**: New query syntax should be intuitive
2. **Session Management**: Users need easy session creation and management
3. **Cross-Session Navigation**: Users need seamless cross-session reference handling

---

## 9. Success Criteria

### 9.1 Functional Requirements

1. **Session Creation**: Users can create and manage sessions
2. **Hierarchy Support**: Project → Topic → Session hierarchy is fully supported
3. **Cross-Session References**: Entities can be linked across sessions
4. **Channel Tracking**: Source channels are tracked and queryable
5. **Temporal Queries**: Users can query entities by time ranges

### 9.2 Performance Requirements

1. **Query Response Time**: Session queries should respond within 100ms
2. **Storage Efficiency**: Session metadata should add minimal overhead (< 10%)
3. **Memory Usage**: System should handle 1000+ concurrent sessions

### 9.3 Integration Requirements

1. **Joplin Compatibility**: Plugin should work with existing Joplin installations
2. **Wiki Link Support**: New syntax should be compatible with existing wiki links
3. **Extraction Pipeline**: Should handle session-aware extraction without breaking existing functionality

---

## 10. Implementation Priority

### 10.1 Phase 1: Core Schema Extension
- Entity/Relation dataclass modifications
- Database schema updates
- Basic session queries

### 10.2 Phase 2: Hierarchy Implementation
- Project-topic-session hierarchy tables
- Hierarchy query methods
- Cross-session reference tables

### 10.3 Phase 3: Integration Enhancement
- Joplin plugin session support
- Extraction pipeline updates
- Wiki link syntax enhancement

### 10.4 Phase 4: Advanced Features
- Complex temporal queries
- Channel-specific features
- Performance optimization

---

## 11. Conclusion

The current Mnemosyne Knowledge Graph provides a solid foundation with its Entity-Relation model, SQLite database, and NetworkX integration. However, significant extensions are needed to support session memory, project-topic-session hierarchy, cross-session referencing, and source channel tracking.

The recommended approach focuses on:
1. **Schema extension** to add session and hierarchy fields
2. **Database schema updates** to support hierarchical storage
3. **Query language enhancement** for session-aware queries
4. **Integration updates** for Joplin plugin and extraction pipeline

This research provides the comprehensive foundation for implementing session memory capabilities while maintaining backward compatibility and performance standards.

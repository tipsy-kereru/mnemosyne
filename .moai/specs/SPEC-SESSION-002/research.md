# SPEC-SESSION-002: Session Integration Layer Research

**Date**: 2026-04-25
**Project**: Mnemosyne Knowledge Graph
**Domain**: Joplin Plugin + Extraction Pipeline Session Integration
**Status**: Deep Research Complete

---

## Executive Summary

This research documents the integration points between SPEC-SESSION-001's session hierarchy system and the Joplin plugin, extraction pipeline, and documentation layers. Three files require modification: the Joplin TypeScript plugin (index.ts), the deterministic code parser (code_parser.py), and the semantic SLM extractor (slm_extractor.py). Additionally, AGENTS.md and CLAUDE.md need updated usage examples.

---

## 1. Current Joplin Plugin Analysis

### 1.1 Architecture (`joplin-plugin/knowledge-graph/src/index.ts`)

The plugin is a single-file TypeScript module (~432 lines) with these key classes/interfaces:

- `KnowledgeGraphPlugin` — main class with in-memory `graphDB: Map<string, KnowledgeGraphEntity>`
- `WikiLink` interface — raw, path, alias, type (note|entity|graph)
- `KnowledgeGraphEntity` interface — id, type, name, properties, version
- `KnowledgeGraphRelation` interface — id, source, target, relationType, properties

### 1.2 Current Domain Detection (lines 346-361)

```typescript
private detectDomain(content: string): 'daily' | 'coding' | 'legal' {
  const patterns = {
    daily: /\b(task|meeting|appointment|reminder|habit|person|contact)\b/i,
    coding: /\b(function|class|module|api|bug|feature|test|dependency)\b/i,
    legal: /\b(statute|clause|case|party|obligation|contract|plaintiff|defendant)\b/i,
  };
  // Returns domain with highest match count
}
```

**Gap**: No session context detection. No frontmatter parsing. No channel identification.

### 1.3 Entity Extraction (lines 363-401)

```typescript
private extractBasedOnDomain(content: string, domain: string): any[] {
  // Regex-based extraction per domain
  // Returns entities with: type, name, properties (source: 'note_extraction')
}
```

**Gap**: No scope_id or source_channel in extracted entities. All entities go to the in-memory Map without scope assignment.

### 1.4 Entity Storage (lines 327-341)

```typescript
for (const entity of entities) {
  const id = `${entity.type}:${entity.name}`;
  this.graphDB.set(id, {
    id, type: entity.type, name: entity.name,
    properties: entity.properties, version: 1,
  });
}
```

**Gap**: No scope_id field in stored entities. No source_channel tracking.

### 1.5 Wiki Link Processing (lines 121-137)

```typescript
private processWikiLinks(text: string): string {
  const wikiLinkPattern = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g;
  // Handles entity:, graph:, and note links
}
```

**Gap**: No scope-aware wiki link syntax. `[[entity:function:parse_config@session:my-session]]` is not supported.

### 1.6 Search (lines 186-208)

In-memory search through `this.graphDB.values()` with type/name filtering.

**Gap**: No scope filtering. No channel filtering. No temporal filtering.

### 1.7 Graph Visualization (lines 266-306)

Basic canvas-based visualization with domain color coding.

**Gap**: No scope hierarchy visualization. No session/project grouping in graph view.

### 1.8 Persistence (lines 404-431)

Uses `plugin.settings.get/set('knowledgeGraph')` for JSON serialization.

**Gap**: No scope persistence. Scope hierarchy is not saved/loaded.

---

## 2. Extraction Pipeline Analysis

### 2.1 TreeSitterExtractor (`core/extraction/deterministic/code_parser.py`)

**Key methods:**
- `extract_file(file_path)` — Extract entities from a single file (lines 46-71)
- `extract_directory(dir_path)` — Recursively extract (lines 238-251)
- `to_wiki_format(entities)` — Convert to wiki markdown (lines 253-272)

**Data model:**
```python
@dataclass
class CodeEntity:
    type: str  # function, class, module
    name: str
    language: str
    file_path: str
    line_start: int
    line_end: int
    properties: Dict[str, Any]
```

**Gap**: CodeEntity has no scope_id or source_channel fields. The extract_file/extract_directory methods accept no session context parameters.

### 2.2 SemanticExtractor (`core/extraction/semantic/slm_extractor.py`)

**Key classes:**
- `GLiNER2Extractor` — NER with model/fallback (lines 35-128)
- `REBELExtractor` — Relation extraction with model/fallback (lines 131-231)
- `SemanticExtractor` — Combined wrapper (lines 234-265)

**Data models:**
```python
@dataclass
class ExtractedEntity:
    type: str
    text: str
    confidence: float
    source: str  # 'gliner2' or 'rule-based'
    start: int
    end: int

@dataclass
class ExtractedRelation:
    subject: str
    relation: str
    object: str
    confidence: float
    source: str  # 'rebel' or 'rule-based'
```

**Gap**: Neither ExtractedEntity nor ExtractedRelation has scope_id or source_channel. The `SemanticExtractor.extract()` method accepts no session context parameters.

---

## 3. Integration Points

### 3.1 KnowledgeGraph API (Already Available from SPEC-001)

```python
# Session-aware entity creation
kg.add_entity(entity, scope_id=session_id, source_channel='discord')

# Session-aware queries
kg.query("entity:function[*]@session:my-session@channel:code")

# Scope management
kg.create_scope('project', 'snake-game')
kg.create_scope('topic', 'game-logic', parent_id=project_id)
kg.create_scope('session', 'impl-move', parent_id=topic_id)
```

### 3.2 Required Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `joplin-plugin/.../index.ts` | MODIFY | Session detection, scope-aware extraction, wiki-link scope syntax |
| `core/extraction/deterministic/code_parser.py` | MODIFY | Add scope_id/source_channel to CodeEntity and extract methods |
| `core/extraction/semantic/slm_extractor.py` | MODIFY | Add scope_id/source_channel to ExtractedEntity/Relation and extract methods |
| `AGENTS.md` | MODIFY | Add session-aware usage patterns |
| `CLAUDE.md` | MODIFY | Add session query examples in usage section |
| `tests/test_integration_session.py` | NEW | Integration tests for extraction pipeline with session context |

---

## 4. Technical Constraints

1. **Joplin Plugin runs in browser context**: Cannot directly import Python modules. Communication with KnowledgeGraph must go through plugin settings or a bridge API.
2. **Tree-sitter extraction is stateless**: Each extract_file call is independent. Scope context must be passed per-invocation.
3. **GLiNER2/REBEL models are lazy-loaded**: Session parameters must flow through the existing extract() API without breaking the lazy-loading pattern.
4. **Backward compatibility**: All existing extraction calls without scope parameters must continue to work unchanged.
5. **Wiki link syntax**: New scope-aware syntax must not break existing `[[note]]`, `[[entity:type:name]]`, `[[graph:query]]` patterns.

---

## 5. Risks

1. **Joplin Plugin bridge**: The plugin stores data in plugin settings (JSON), not directly in the SQLite knowledge.db. Session-aware entities created in the plugin may need a synchronization mechanism.
2. **Scope context propagation**: Extraction methods that call sub-methods (e.g., `_extract_python`, `_extract_js_ts`) need to thread scope_id through without changing method signatures excessively.
3. **TypeScript scope model**: The plugin's in-memory graphDB uses Map<string, Entity>, not the SQLite-backed KnowledgeGraph. Session hierarchy must be represented differently in the plugin context.

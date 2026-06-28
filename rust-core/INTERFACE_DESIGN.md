# Rust Core PyO3 Interface Design

## Version
- **Document Version**: 1.0.0
- **Created**: 2025-06-28
- **Status**: Design Phase

## Overview

This document defines the PyO3 interface for the extended Rust core, specifying which Python operations will be accelerated by Rust implementation.

---

## Design Principles

1. **Type Safety**: Use well-defined PyO3 types for all boundaries
2. **Error Handling**: Structured error types with Python-friendly messages
3. **Backward Compatibility**: Maintain existing Python API shape
4. **Performance**: Minimize serialization overhead at boundaries
5. **Testability**: Each function independently testable

---

## Current Interface (Baseline)

```rust
// mnemosyne-core/src/lib.rs (current: 107 lines)

#[pyfunction]
fn fast_glob_markdown(dir_path: &str) -> PyResult<Vec<String>>

#[pyfunction]
fn fast_rebuild_index(
    wiki_root: &str,
    entity_pages: Vec<String>,
    source_pages: Vec<String>,
    updated_at: &str,
    editor_guidance: Vec<String>,
) -> PyResult<String>
```

**Usage in Python:**
```python
from mnemosyne import mnemosyne_core

files = mnemosyne_core.fast_glob_markdown("/path/to/wiki")
index_content = mnemosyne_core.fast_rebuild_index(...)
```

---

## Proposed Extended Interface

### Module Structure

```rust
// src/lib.rs
pub mod wiki;
pub mod graph;
pub mod db;
pub mod ingest;
pub mod types;

use pyo3::prelude::*;

#[pymodule]
fn mnemosyne_core(_py: Python, m: &PyModule) -> PyResult<()> {
    // Wiki module
    let wiki_module = PyModule::new(_py, "wiki")?;
    wiki_module.add_function(wrap_pyfunction!(wiki::rebuild_all, m)?)?;
    wiki_module.add_function(wrap_pyfunction!(wiki::write_entity_page, m)?)?;
    wiki_module.add_function(wrap_pyfunction!(wiki::write_source_page, m)?)?;
    wiki_module.add_function(wrap_pyfunction!(wiki::glob_markdown, m)?)?;
    wiki_module.add_function(wrap_pyfunction!(wiki::rebuild_index, m)?)?;
    m.add_submodule(wiki_module)?;

    // Graph module
    let graph_module = PyModule::new(_py, "graph")?;
    graph_module.add_function(wrap_pyfunction!(graph::query_entities, m)?)?;
    graph_module.add_function(wrap_pyfunction!(graph::query_relations, m)?)?;
    graph_module.add_function(wrap_pyfunction!(graph::find_path, m)?)?;
    graph_module.add_function(wrap_pyfunction!(graph::get_stats, m)?)?;
    m.add_submodule(graph_module)?;

    // Database module
    let db_module = PyModule::new(_py, "db")?;
    db_module.add_function(wrap_pyfunction!(db::execute_query, m)?)?;
    db_module.add_function(wrap_pyfunction!(db::batch_insert_entities, m)?)?;
    db_module.add_function(wrap_pyfunction!(db::batch_insert_relations, m)?)?;
    m.add_submodule(db_module)?;

    Ok(())
}
```

---

## Wiki Module

### 1. `wiki::rebuild_all`

**Purpose**: Regenerate all wiki pages from graph data (parallel)

```rust
#[pyfunction]
pub fn rebuild_all(
    wiki_root: &str,
    db_path: &str,
    py: Python,
) -> PyResult<WikiUpdate>
```

**Parameters:**
- `wiki_root`: Path to wiki directory
- `db_path`: Path to SQLite database

**Returns:**
```rust
#[pyclass]
#[derive(Clone)]
pub struct WikiUpdate {
    #[pyo3(get, set)]
    pub paths: Vec<String>,
    #[pyo3(get, set)]
    pub entity_count: usize,
    #[pyo3(get, set)]
    pub source_count: usize,
    #[pyo3(get, set)]
    pub duration_ms: u64,
}
```

**Python Usage:**
```python
from mnemosyne.mnemosyne_core.wiki import rebuild_all

update = rebuild_all(
    wiki_root="~/mnemosyne/wiki",
    db_path="~/mnemosyne/graph/knowledge.db"
)
print(f"Updated {update.entity_count} entity pages")
print(f"Updated {len(update.paths)} files in {update.duration_ms}ms")
```

---

### 2. `wiki::write_entity_page`

**Purpose**: Write a single entity wiki page with frontmatter

```rust
#[pyfunction]
pub fn write_entity_page(
    wiki_root: &str,
    entity: &EntityData,
    relations: Vec<RelationData>,
    sources: Vec<SourceData>,
) -> PyResult<String>
```

**Parameters:**
```rust
#[pyclass]
#[derive(Clone, Debug)]
pub struct EntityData {
    #[pyo3(get, set)]
    pub id: String,
    #[pyo3(get, set)]
    pub label: String,
    #[pyo3(get, set)]
    pub entity_type: String,
    #[pyo3(get, set)]
    pub properties: String,  // JSON string
    #[pyo3(get, set)]
    pub scope_id: String,
    #[pyo3(get, set)]
    pub source_channel: String,
}

#[pyclass]
#[derive(Clone, Debug)]
pub struct RelationData {
    #[pyo3(get, set)]
    pub source: String,
    #[pyo3(get, set)]
    pub relation: String,
    #[pyo3(get, set)]
    pub target: String,
}

#[pyclass]
#[derive(Clone, Debug)]
pub struct SourceData {
    #[pyo3(get, set)]
    pub source_file: String,
    #[pyo3(get, set)]
    pub source_id: String,
}
```

**Returns:** Path to written file

**Python Usage:**
```python
from mnemosyne.mnemosyne_core.wiki import write_entity_page, EntityData, RelationData

entity = EntityData(
    id="func-123",
    label="authenticate",
    entity_type="function",
    properties='{"language": "python", "complexity": 5}',
    scope_id="global",
    source_channel="cli"
)

relations = [
    RelationData(source="func-123", relation="calls", target="func-456")
]

path = write_entity_page(
    wiki_root="~/mnemosyne/wiki",
    entity=entity,
    relations=relations,
    sources=[]
)
```

---

### 3. `wiki::write_source_page`

**Purpose**: Write a source page with extracted entities

```rust
#[pyfunction]
pub fn write_source_page(
    wiki_root: &str,
    source: &SourcePageData,
    entities: Vec<EntityData>,
    relations: Vec<RelationData>,
) -> PyResult<String>
```

**Parameters:**
```rust
#[pyclass]
#[derive(Clone, Debug)]
pub struct SourcePageData {
    #[pyo3(get, set)]
    pub source: String,
    #[pyo3(get, set)]
    pub domain: String,
    #[pyo3(get, set)]
    pub original_source: String,
    #[pyo3(get, set)]
    pub raw_path: String,
    #[pyo3(get, set)]
    pub content_hash: String,
    #[pyo3(get, set)]
    pub scope_id: String,
    #[pyo3(get, set)]
    pub source_channel: String,
}
```

---

### 4. `wiki::glob_markdown` (Enhanced)

**Purpose**: Find all markdown files in a directory (current: `fast_glob_markdown`)

```rust
#[pyfunction]
pub fn glob_markdown(
    dir_path: &str,
    recursive: bool,
) -> PyResult<Vec<String>>
```

**Enhancement:** Add `recursive` parameter (currently always recursive)

---

### 5. `wiki::rebuild_index` (Enhanced)

**Purpose:** Generate index.md content (current: `fast_rebuild_index`)

```rust
#[pyfunction]
pub fn rebuild_index(
    wiki_root: &str,
    entity_pages: Vec<String>,
    source_pages: Vec<String>,
    options: &IndexOptions,
) -> PyResult<String>
```

**New Parameters:**
```rust
#[pyclass]
#[derive(Clone, Debug)]
pub struct IndexOptions {
    #[pyo3(get, set)]
    pub updated_at: String,
    #[pyo3(get, set)]
    pub editor_guidance: Vec<String>,
    #[pyo3(get, set)]
    pub include_log_link: bool,
}
```

---

## Graph Module

### 1. `graph::query_entities`

**Purpose**: Query entities from graph (FTS + filters)

```rust
#[pyfunction]
pub fn query_entities(
    db_path: &str,
    query: &EntityQuery,
) -> PyResult<Vec<EntityData>>
```

**Parameters:**
```rust
#[pyclass]
#[derive(Clone, Debug)]
pub struct EntityQuery {
    #[pyo3(get, set)]
    pub search_term: Option<String>,
    #[pyo3(get, set)]
    pub entity_type: Option<String>,
    #[pyo3(get, set)]
    pub scope_id: Option<String>,
    #[pyo3(get, set)]
    pub limit: usize,
}
```

**Python Usage:**
```python
from mnemosyne.mnemosyne_core.graph import query_entities, EntityQuery

query = EntityQuery(
    search_term="authenticate",
    entity_type="function",
    scope_id=None,
    limit=100
)

entities = query_entities(
    db_path="~/mnemosyne/graph/knowledge.db",
    query=query
)
```

---

### 2. `graph::query_relations`

**Purpose**: Query relations with filters

```rust
#[pyfunction]
pub fn query_relations(
    db_path: &str,
    query: &RelationQuery,
) -> PyResult<Vec<RelationData>>
```

**Parameters:**
```rust
#[pyclass]
#[derive(Clone, Debug)]
pub struct RelationQuery {
    #[pyo3(get, set)]
    pub source: Option<String>,
    #[pyo3(get, set)]
    pub relation: Option<String>,
    #[pyo3(get, set)]
    pub target: Option<String>,
    #[pyo3(get, set)]
    pub scope_id: Option<String>,
    #[pyo3(get, set)]
    pub limit: usize,
}
```

---

### 3. `graph::find_path`

**Purpose**: Find shortest path between entities

```rust
#[pyfunction]
pub fn find_path(
    db_path: &str,
    source_id: &str,
    target_id: &str,
    max_depth: usize,
) -> PyResult<Vec<String>>
```

**Returns:** List of entity IDs in the path

---

### 4. `graph::get_stats`

**Purpose:** Get graph statistics

```rust
#[pyfunction]
pub fn get_stats(
    db_path: &str,
) -> PyResult<GraphStats>
```

**Returns:**
```rust
#[pyclass]
#[derive(Clone, Debug)]
pub struct GraphStats {
    #[pyo3(get, set)]
    pub entity_count: usize,
    #[pyo3(get, set)]
    pub relation_count: usize,
    #[pyo3(get, set)]
    pub scope_count: usize,
    #[pyo3(get, set)]
    pub type_counts: String,  // JSON: {"function": 120, "class": 45}
}
```

---

## Database Module

### 1. `db::execute_query`

**Purpose:** Execute raw SQLite query

```rust
#[pyfunction]
pub fn execute_query(
    db_path: &str,
    sql: &str,
    params: Vec<PyObject>,  // Bound parameters
) -> PyResult<QueryResult>
```

**Returns:**
```rust
#[pyclass]
#[derive(Clone)]
pub struct QueryResult {
    #[pyo3(get, set)]
    pub rows: Vec<String>,  // JSON array of row objects
    #[pyo3(get, set)]
    pub row_count: usize,
}
```

---

### 2. `db::batch_insert_entities`

**Purpose:** Bulk insert entities (optimized)

```rust
#[pyfunction]
pub fn batch_insert_entities(
    db_path: &str,
    entities: Vec<EntityData>,
) -> PyResult<BatchResult>
```

**Returns:**
```rust
#[pyclass]
#[derive(Clone)]
pub struct BatchResult {
    #[pyo3(get, set)]
    pub inserted: usize,
    #[pyo3(get, set)]
    pub updated: usize,
    #[pyo3(get, set)]
    pub failed: usize,
}
```

---

## Error Handling

### Custom Error Types

```rust
pub enum MnemosyneError {
    Io(io::Error),
    Db(rusqlite::Error),
    Serialization(serde_json::Error),
    WikiLock(String),
    InvalidInput(String),
}

impl From<MnemosyneError> for PyErr {
    fn from(err: MnemosyneError) -> PyErr {
        match err {
            MnemosyneError::Io(e) => PyIOError::new_err(e.to_string()),
            MnemosyneError::Db(e) => PyRuntimeError::new_err(e.to_string()),
            MnemosyneError::WikiLock(msg) => {
                PyValueError::new_err(format!("Wiki lock error: {}", msg))
            }
            // ... other cases
        }
    }
}
```

### Python Exception Types

```python
# Python side
class MnemosyneError(Exception):
    """Base exception for Mnemosyne errors."""
    pass

class WikiLockError(MnemosyneError):
    """Raised when wiki write lock cannot be acquired."""
    pass

class DatabaseError(MnemosyneError):
    """Raised for database-related errors."""
    pass
```

---

## Type Conversion Layer

### Python → Rust

| Python Type | Rust Type | Notes |
|-------------|-----------|-------|
| `str` | `&str` / `String` | UTF-8 assumed |
| `List[str]` | `Vec<String>` | Via PyO3 `FromPyObject` |
| `Dict[str, Any]` | `HashMap<String, Value>` | JSON serialization |
| `bytes` | `&[u8]` | For binary data |
| `datetime` | `i64` (Unix timestamp) | Simplified |

### Rust → Python

| Rust Type | Python Type | Notes |
|-----------|-------------|-------|
| `String` | `str` | Via `IntoPy` |
| `Vec<T>` | `List[T]` | Via `IntoPy` |
| `HashMap<K,V>` | `Dict[K,V]` | Via `IntoPy` |
| structs | `dataclass` | Via `#[pyclass]` |

---

## Performance Considerations

### Serialization Hotspots

| Operation | Current (Python) | Rust Improvement |
|-----------|------------------|-------------------|
| Entity JSON parse | `json.loads()` (Python) | `serde_json::from_str()` (Rust) |
| Wiki page build | String concat (Python) | `format!` + `rayon` (Rust) |
| Graph traversal | NetworkX (Python) | `petgraph` (Rust) |
| Batch insert | Individual INSERT | Transaction + batch (Rust) |

### Minimizing Boundary Crossings

**DO:**
```python
# Single call, bulk processing
entities = query_entities(db_path, query)  # Returns 1000 entities
```

**DON'T:**
```python
# 1000 calls across boundary
for entity_id in ids:
    entity = get_entity(db_path, entity_id)  # Slow!
```

---

## Testing Strategy

### Unit Tests (Rust)

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_glob_markdown() {
        let result = glob_markdown("/test/path", true);
        assert!(result.is_ok());
    }
}
```

### Integration Tests (Python)

```python
def test_wiki_rebuild():
    from mnemosyne.mnemosyne_core.wiki import rebuild_all

    update = rebuild_all(
        wiki_root=tmp_path,
        db_path=test_db,
    )
    assert update.entity_count > 0
    assert update.duration_ms < 5000  # 5 second SLA
```

### Benchmarks

```rust
#[bench]
fn bench_rebuild_all(b: &mut Bencher) {
    b.iter(|| {
        rebuild_all(wiki_root, db_path, Python::acquire_gil())
    });
}
```

---

## Migration Path

### Phase 1: Add New Functions
- Keep existing `fast_glob_markdown`, `fast_rebuild_index`
- Add new functions with different names
- No breaking changes

### Phase 2: Deprecate Old Names
- Add `#[deprecated]` attributes
- Emit warnings
- Update documentation

### Phase 3: Remove Old Functions
- Remove deprecated functions in next major version

---

## Open Questions

| ID | Question | Proposal | Status |
|----|----------|----------|--------|
| OQ-1 | Should we use `PyObject` for properties? | Use JSON string for now, migrate to `PyObject` later | Open |
| OQ-2 | How to handle large result sets? | Add pagination parameters (`offset`, `limit`) | Open |
| OQ-3 | Should we support async? | No, keep it simple for now | Decided |

---

## Appendix: Example Python Integration

```python
# core/wiki/llm_wiki.py (refactored)

from mnemosyne import mnemosyne_core

class LLMWikiMaintainer:
    def rebuild_from_graph(self, db_path, *, dry_run=False):
        """Regenerate wiki pages using Rust core."""
        if dry_run:
            # Preview mode: don't write files
            update = mnemosyne_core.wiki.rebuild_all_preview(
                wiki_root=str(self.wiki_root),
                db_path=str(db_path),
            )
        else:
            update = mnemosyne_core.wiki.rebuild_all(
                wiki_root=str(self.wiki_root),
                db_path=str(db_path),
            )

        return WikiUpdate(
            paths=[Path(p) for p in update.paths],
            entity_count=update.entity_count,
            source_count=update.source_count,
            duration_ms=update.duration_ms,
        )
```

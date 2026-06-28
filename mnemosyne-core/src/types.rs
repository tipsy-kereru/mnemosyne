//! Shared types for PyO3 bindings.

use pyo3::prelude::*;
use pyo3::exceptions::{PyIOError, PyRuntimeError, PyValueError};
use serde::{Deserialize, Serialize};

// ============================================================================
// Wiki Types
// ============================================================================

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
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

impl WikiUpdate {
    pub fn new() -> Self {
        Self {
            paths: Vec::new(),
            entity_count: 0,
            source_count: 0,
            duration_ms: 0,
        }
    }
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EntityData {
    #[pyo3(get, set)]
    pub id: String,
    #[pyo3(get, set)]
    pub label: String,
    #[pyo3(get, set)]
    pub entity_type: String,
    #[pyo3(get, set)]
    pub properties: String, // JSON string
    #[pyo3(get, set)]
    pub scope_id: String,
    #[pyo3(get, set)]
    pub source_channel: String,
}

#[pymethods]
impl EntityData {
    #[new]
    fn new(
        id: String,
        label: String,
        entity_type: String,
        properties: String,
        scope_id: String,
        source_channel: String,
    ) -> Self {
        Self {
            id,
            label,
            entity_type,
            properties,
            scope_id,
            source_channel,
        }
    }
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RelationData {
    #[pyo3(get, set)]
    pub source: String,
    #[pyo3(get, set)]
    pub relation: String,
    #[pyo3(get, set)]
    pub target: String,
}

#[pymethods]
impl RelationData {
    #[new]
    fn new(source: String, relation: String, target: String) -> Self {
        Self {
            source,
            relation,
            target,
        }
    }
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SourceData {
    #[pyo3(get, set)]
    pub source_file: String,
    #[pyo3(get, set)]
    pub source_id: String,
}

#[pymethods]
impl SourceData {
    #[new]
    fn new(source_file: String, source_id: String) -> Self {
        Self {
            source_file,
            source_id,
        }
    }
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
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

#[pymethods]
impl SourcePageData {
    #[new]
    fn new(
        source: String,
        domain: String,
        original_source: String,
        raw_path: String,
        content_hash: String,
        scope_id: String,
        source_channel: String,
    ) -> Self {
        Self {
            source,
            domain,
            original_source,
            raw_path,
            content_hash,
            scope_id,
            source_channel,
        }
    }
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct IndexOptions {
    #[pyo3(get, set)]
    pub updated_at: String,
    #[pyo3(get, set)]
    pub editor_guidance: Vec<String>,
    #[pyo3(get, set)]
    pub include_log_link: bool,
}

#[pymethods]
impl IndexOptions {
    #[new]
    fn new(updated_at: String, editor_guidance: Vec<String>, include_log_link: bool) -> Self {
        Self {
            updated_at,
            editor_guidance,
            include_log_link,
        }
    }
}

// ============================================================================
// Graph Types
// ============================================================================

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
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

#[pymethods]
impl EntityQuery {
    #[new]
    #[pyo3(signature = (search_term=None, entity_type=None, scope_id=None, limit=100))]
    fn new(
        search_term: Option<String>,
        entity_type: Option<String>,
        scope_id: Option<String>,
        limit: usize,
    ) -> Self {
        Self {
            search_term,
            entity_type,
            scope_id,
            limit,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "EntityQuery(search_term={:?}, type={:?}, scope={:?}, limit={})",
            self.search_term, self.entity_type, self.scope_id, self.limit
        )
    }
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
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

#[pymethods]
impl RelationQuery {
    #[new]
    #[pyo3(signature = (source=None, relation=None, target=None, scope_id=None, limit=100))]
    fn new(
        source: Option<String>,
        relation: Option<String>,
        target: Option<String>,
        scope_id: Option<String>,
        limit: usize,
    ) -> Self {
        Self {
            source,
            relation,
            target,
            scope_id,
            limit,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "RelationQuery(source={:?}, relation={:?}, target={:?}, scope={:?}, limit={})",
            self.source, self.relation, self.target, self.scope_id, self.limit
        )
    }
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GraphStats {
    #[pyo3(get, set)]
    pub entity_count: usize,
    #[pyo3(get, set)]
    pub relation_count: usize,
    #[pyo3(get, set)]
    pub scope_count: usize,
    #[pyo3(get, set)]
    pub type_counts: String, // JSON: {"function": 120, "class": 45}
}

#[pymethods]
impl GraphStats {
    #[new]
    fn new(entity_count: usize, relation_count: usize, scope_count: usize, type_counts: String) -> Self {
        Self {
            entity_count,
            relation_count,
            scope_count,
            type_counts,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "GraphStats(entities={}, relations={}, scopes={}, types={})",
            self.entity_count, self.relation_count, self.scope_count, self.type_counts
        )
    }
}

// ============================================================================
// Database Types
// ============================================================================

#[pyclass]
#[derive(Clone, Debug)]
pub struct QueryResult {
    #[pyo3(get, set)]
    pub rows: String, // JSON array
    #[pyo3(get, set)]
    pub row_count: usize,
}

#[pyclass]
#[derive(Clone, Debug)]
pub struct BatchResult {
    #[pyo3(get, set)]
    pub inserted: usize,
    #[pyo3(get, set)]
    pub updated: usize,
    #[pyo3(get, set)]
    pub failed: usize,
}

// ============================================================================
// Error Types
// ============================================================================

#[derive(Debug, thiserror::Error)]
pub enum MnemosyneError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Database error: {0}")]
    Db(#[from] rusqlite::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("Wiki lock error: {0}")]
    WikiLock(String),

    #[error("Invalid input: {0}")]
    InvalidInput(String),
}

impl From<MnemosyneError> for PyErr {
    fn from(err: MnemosyneError) -> PyErr {
        match err {
            MnemosyneError::Io(e) => PyIOError::new_err(e.to_string()),
            MnemosyneError::Db(e) => PyRuntimeError::new_err(e.to_string()),
            MnemosyneError::Json(e) => PyValueError::new_err(e.to_string()),
            MnemosyneError::WikiLock(msg) => {
                PyValueError::new_err(format!("Wiki lock error: {}", msg))
            }
            MnemosyneError::InvalidInput(msg) => PyValueError::new_err(msg),
        }
    }
}

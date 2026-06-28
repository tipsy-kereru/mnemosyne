//! Database operations module.
//!
//! Provides high-performance database operations with transaction support.

use crate::types::{BatchResult, MnemosyneError, QueryResult};
use pyo3::prelude::*;
use rusqlite::{Connection, params_from_iter, Transaction};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ============================================================================
// Database Types
// ============================================================================

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EntityInsert {
    #[pyo3(get, set)]
    pub id: String,
    #[pyo3(get, set)]
    pub entity_type: String,
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub properties: String, // JSON
    #[pyo3(get, set)]
    pub created_at: String,
    #[pyo3(get, set)]
    pub updated_at: String,
    #[pyo3(get, set)]
    pub version: i32,
    #[pyo3(get, set)]
    pub scope_id: Option<String>,
    #[pyo3(get, set)]
    pub source_channel: String,
    #[pyo3(get, set)]
    pub content_hash: Option<String>,
}

#[pymethods]
impl EntityInsert {
    #[new]
    #[pyo3(signature = (id, entity_type, name, properties, created_at, updated_at, version=1, scope_id=None, source_channel="legacy".to_string(), content_hash=None))]
    fn new(
        id: String,
        entity_type: String,
        name: String,
        properties: String,
        created_at: String,
        updated_at: String,
        version: i32,
        scope_id: Option<String>,
        source_channel: String,
        content_hash: Option<String>,
    ) -> Self {
        Self {
            id,
            entity_type,
            name,
            properties,
            created_at,
            updated_at,
            version,
            scope_id,
            source_channel,
            content_hash,
        }
    }
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RelationInsert {
    #[pyo3(get, set)]
    pub id: String,
    #[pyo3(get, set)]
    pub source_id: String,
    #[pyo3(get, set)]
    pub target_id: String,
    #[pyo3(get, set)]
    pub relation_type: String,
    #[pyo3(get, set)]
    pub properties: String, // JSON
    #[pyo3(get, set)]
    pub created_at: String,
    #[pyo3(get, set)]
    pub version: i32,
    #[pyo3(get, set)]
    pub scope_id: Option<String>,
    #[pyo3(get, set)]
    pub source_channel: String,
}

#[pymethods]
impl RelationInsert {
    #[new]
    #[pyo3(signature = (id, source_id, target_id, relation_type, properties, created_at, version=1, scope_id=None, source_channel="legacy".to_string()))]
    fn new(
        id: String,
        source_id: String,
        target_id: String,
        relation_type: String,
        properties: String,
        created_at: String,
        version: i32,
        scope_id: Option<String>,
        source_channel: String,
    ) -> Self {
        Self {
            id,
            source_id,
            target_id,
            relation_type,
            properties,
            created_at,
            version,
            scope_id,
            source_channel,
        }
    }
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EntityUpdate {
    #[pyo3(get, set)]
    pub id: String,
    #[pyo3(get, set)]
    pub entity_type: String,
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub properties: String, // JSON
    #[pyo3(get, set)]
    pub updated_at: String,
    #[pyo3(get, set)]
    pub scope_id: Option<String>,
    #[pyo3(get, set)]
    pub source_channel: String,
    #[pyo3(get, set)]
    pub content_hash: Option<String>,
}

#[pymethods]
impl EntityUpdate {
    #[new]
    #[pyo3(signature = (id, entity_type, name, properties, updated_at, scope_id=None, source_channel="legacy".to_string(), content_hash=None))]
    fn new(
        id: String,
        entity_type: String,
        name: String,
        properties: String,
        updated_at: String,
        scope_id: Option<String>,
        source_channel: String,
        content_hash: Option<String>,
    ) -> Self {
        Self {
            id,
            entity_type,
            name,
            properties,
            updated_at,
            scope_id,
            source_channel,
            content_hash,
        }
    }
}

// ============================================================================
// Database Operations
// ============================================================================

/// Execute a raw SQL query and return results.
///
/// Args:
///     db_path: Path to SQLite database
///     sql: SQL query to execute (can contain ? placeholders)
///     params: Optional list of parameters for placeholders
///
/// Returns:
///     QueryResult with rows as JSON array and row count
#[pyfunction]
pub fn execute_query(
    db_path: String,
    sql: String,
    params: Option<Vec<String>>,
) -> PyResult<QueryResult> {
    let conn = Connection::open(db_path)
        .map_err(|e| MnemosyneError::Db(e))?;

    let mut rows = Vec::new();

    if let Some(param_list) = params {
        let param_refs: Vec<&dyn rusqlite::ToSql> = param_list.iter().map(|p| p as &dyn rusqlite::ToSql).collect();
        let mut stmt = conn.prepare(&sql)
            .map_err(|e| MnemosyneError::Db(e))?;

        let column_count = stmt.column_count();
        let column_names: Vec<String> = (0..column_count)
            .map(|i| match stmt.column_name(i) {
                Ok(name) => name.to_string(),
                Err(_) => format!("col_{}", i),
            })
            .collect();

        let query_rows = stmt.query_map(params_from_iter(param_refs.iter()), |row| {
            let mut row_map = HashMap::new();
            for i in 0..column_count {
                let name = column_names[i].clone();

                // Try to get value as different types
                let value: serde_json::Value = if let Ok(Some(v)) = row.get::<_, Option<String>>(i) {
                    v.into()
                } else if let Ok(Some(v)) = row.get::<_, Option<i64>>(i) {
                    v.into()
                } else if let Ok(Some(v)) = row.get::<_, Option<f64>>(i) {
                    v.into()
                } else if let Ok(Some(v)) = row.get::<_, Option<bool>>(i) {
                    v.into()
                } else {
                    serde_json::Value::Null
                };

                row_map.insert(name, value);
            }
            Ok(row_map)
        })
        .map_err(|e| MnemosyneError::Db(e))?;

        for row_result in query_rows {
            rows.push(row_result.map_err(|e| MnemosyneError::Db(e))?);
        }
    } else {
        let mut stmt = conn.prepare(&sql)
            .map_err(|e| MnemosyneError::Db(e))?;

        let column_count = stmt.column_count();
        let column_names: Vec<String> = (0..column_count)
            .map(|i| match stmt.column_name(i) {
                Ok(name) => name.to_string(),
                Err(_) => format!("col_{}", i),
            })
            .collect();

        let query_rows = stmt.query_map([], |row| {
            let mut row_map = HashMap::new();
            for i in 0..column_count {
                let name = column_names[i].clone();

                let value: serde_json::Value = if let Ok(Some(v)) = row.get::<_, Option<String>>(i) {
                    v.into()
                } else if let Ok(Some(v)) = row.get::<_, Option<i64>>(i) {
                    v.into()
                } else if let Ok(Some(v)) = row.get::<_, Option<f64>>(i) {
                    v.into()
                } else if let Ok(Some(v)) = row.get::<_, Option<bool>>(i) {
                    v.into()
                } else {
                    serde_json::Value::Null
                };

                row_map.insert(name, value);
            }
            Ok(row_map)
        })
        .map_err(|e| MnemosyneError::Db(e))?;

        for row_result in query_rows {
            rows.push(row_result.map_err(|e| MnemosyneError::Db(e))?);
        }
    }

    let rows_json = serde_json::to_string(&rows)
        .map_err(|e| MnemosyneError::Json(e))?;

    Ok(QueryResult {
        rows: rows_json,
        row_count: rows.len(),
    })
}

/// Insert multiple entities in a single transaction.
///
/// Args:
///     db_path: Path to SQLite database
///     entities: List of EntityInsert objects
///
/// Returns:
///     BatchResult with inserted/updated/failed counts
#[pyfunction]
pub fn batch_insert_entities(
    db_path: String,
    entities: Vec<EntityInsert>,
) -> PyResult<BatchResult> {
    let conn = Connection::open(db_path)
        .map_err(|e| MnemosyneError::Db(e))?;

    let tx = conn.unchecked_transaction()
        .map_err(|e| MnemosyneError::Db(e))?;

    let mut inserted = 0;
    let mut updated = 0;
    let mut failed = 0;

    for entity in entities {
        let result = insert_or_update_entity(&tx, &entity);
        match result {
            Ok(true) => inserted += 1,
            Ok(false) => updated += 1,
            Err(_) => failed += 1,
        }
    }

    tx.commit()
        .map_err(|e| MnemosyneError::Db(e))?;

    Ok(BatchResult {
        inserted,
        updated,
        failed,
    })
}

/// Insert multiple relations in a single transaction.
///
/// Args:
///     db_path: Path to SQLite database
///     relations: List of RelationInsert objects
///
/// Returns:
///     BatchResult with inserted/updated/failed counts
#[pyfunction]
pub fn batch_insert_relations(
    db_path: String,
    relations: Vec<RelationInsert>,
) -> PyResult<BatchResult> {
    let conn = Connection::open(db_path)
        .map_err(|e| MnemosyneError::Db(e))?;

    let tx = conn.unchecked_transaction()
        .map_err(|e| MnemosyneError::Db(e))?;

    let mut inserted = 0;
    let mut updated = 0;
    let mut failed = 0;

    for relation in relations {
        let result = insert_or_update_relation(&tx, &relation);
        match result {
            Ok(true) => inserted += 1,
            Ok(false) => updated += 1,
            Err(_) => failed += 1,
        }
    }

    tx.commit()
        .map_err(|e| MnemosyneError::Db(e))?;

    Ok(BatchResult {
        inserted,
        updated,
        failed,
    })
}

/// Update multiple entities in a single transaction.
///
/// Args:
///     db_path: Path to SQLite database
///     entities: List of EntityUpdate objects
///     skip_unchanged: If true, skip update when content_hash matches
///
/// Returns:
///     BatchResult with inserted/updated/failed counts
#[pyfunction]
pub fn batch_update_entities(
    db_path: String,
    entities: Vec<EntityUpdate>,
    skip_unchanged: bool,
) -> PyResult<BatchResult> {
    let conn = Connection::open(db_path)
        .map_err(|e| MnemosyneError::Db(e))?;

    let tx = conn.unchecked_transaction()
        .map_err(|e| MnemosyneError::Db(e))?;

    let mut inserted = 0;
    let mut updated = 0;
    let mut failed = 0;

    for entity in entities {
        let result = update_entity(&tx, &entity, skip_unchanged);
        match result {
            Ok(true) => updated += 1,
            Ok(false) => { /* skipped */ }
            Err(_) => failed += 1,
        }
    }

    tx.commit()
        .map_err(|e| MnemosyneError::Db(e))?;

    Ok(BatchResult {
        inserted,
        updated,
        failed,
    })
}

// ============================================================================
// Internal Helper Functions
// ============================================================================

/// Insert or update an entity (UPSERT logic).
/// Returns Ok(true) if inserted, Ok(false) if updated, Err on failure.
fn insert_or_update_entity(tx: &Transaction, entity: &EntityInsert) -> Result<bool, MnemosyneError> {
    // Check if entity exists
    let exists: bool = tx.query_row(
        "SELECT EXISTS(SELECT 1 FROM entities WHERE id = ? LIMIT 1)",
        [&entity.id],
        |row| row.get(0),
    ).unwrap_or(false);

    if exists {
        // Update existing entity
        tx.execute(
            "UPDATE entities SET type = ?, name = ?, properties = ?, updated_at = ?, version = ?, scope_id = ?, source_channel = ?, content_hash = ? WHERE id = ?",
            [
                &entity.entity_type,
                &entity.name,
                &entity.properties,
                &entity.updated_at,
                &entity.version.to_string(),
                &entity.scope_id.clone().unwrap_or_else(|| "NULL".to_string()),
                &entity.source_channel,
                &entity.content_hash.clone().unwrap_or_else(|| "NULL".to_string()),
                &entity.id,
            ],
        ).map_err(|e| MnemosyneError::Db(e))?;
        Ok(false)
    } else {
        // Insert new entity
        tx.execute(
            "INSERT INTO entities (id, type, name, properties, created_at, updated_at, version, scope_id, source_channel, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                &entity.id,
                &entity.entity_type,
                &entity.name,
                &entity.properties,
                &entity.created_at,
                &entity.updated_at,
                &entity.version.to_string(),
                &entity.scope_id.clone().unwrap_or_else(|| "NULL".to_string()),
                &entity.source_channel,
                &entity.content_hash.clone().unwrap_or_else(|| "NULL".to_string()),
            ],
        ).map_err(|e| MnemosyneError::Db(e))?;
        Ok(true)
    }
}

/// Insert or update a relation (UPSERT logic).
/// Returns Ok(true) if inserted, Ok(false) if updated, Err on failure.
fn insert_or_update_relation(tx: &Transaction, relation: &RelationInsert) -> Result<bool, MnemosyneError> {
    // Check if relation exists
    let exists: bool = tx.query_row(
        "SELECT EXISTS(SELECT 1 FROM relations WHERE id = ? LIMIT 1)",
        [&relation.id],
        |row| row.get(0),
    ).unwrap_or(false);

    if exists {
        // Update existing relation
        tx.execute(
            "UPDATE relations SET source_id = ?, target_id = ?, relation_type = ?, properties = ?, version = ?, scope_id = ?, source_channel = ? WHERE id = ?",
            [
                &relation.source_id,
                &relation.target_id,
                &relation.relation_type,
                &relation.properties,
                &relation.version.to_string(),
                &relation.scope_id.clone().unwrap_or_else(|| "NULL".to_string()),
                &relation.source_channel,
                &relation.id,
            ],
        ).map_err(|e| MnemosyneError::Db(e))?;
        Ok(false)
    } else {
        // Insert new relation
        tx.execute(
            "INSERT INTO relations (id, source_id, target_id, relation_type, properties, created_at, version, scope_id, source_channel) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                &relation.id,
                &relation.source_id,
                &relation.target_id,
                &relation.relation_type,
                &relation.properties,
                &relation.created_at,
                &relation.version.to_string(),
                &relation.scope_id.clone().unwrap_or_else(|| "NULL".to_string()),
                &relation.source_channel,
            ],
        ).map_err(|e| MnemosyneError::Db(e))?;
        Ok(true)
    }
}

/// Update an entity with optional skip-unchanged optimization.
/// Returns Ok(true) if updated, Ok(false) if skipped, Err on failure.
fn update_entity(tx: &Transaction, entity: &EntityUpdate, skip_unchanged: bool) -> Result<bool, MnemosyneError> {
    // Check if entity exists
    let exists: bool = tx.query_row(
        "SELECT EXISTS(SELECT 1 FROM entities WHERE id = ? LIMIT 1)",
        [&entity.id],
        |row| row.get(0),
    ).unwrap_or(false);

    if !exists {
        return Err(MnemosyneError::InvalidInput(format!("Entity not found: {}", entity.id)));
    }

    // Check for skip-unchanged optimization
    if skip_unchanged && entity.content_hash.is_some() {
        let stored_hash: Option<String> = tx.query_row(
            "SELECT content_hash FROM entities WHERE id = ?",
            [&entity.id],
            |row| row.get(0),
        ).ok();

        if stored_hash == entity.content_hash {
            // Content unchanged, skip update
            return Ok(false);
        }
    }

    // Perform update
    tx.execute(
        "UPDATE entities SET type = ?, name = ?, properties = ?, updated_at = ?, scope_id = ?, source_channel = ?, content_hash = COALESCE(?, content_hash) WHERE id = ?",
        [
            &entity.entity_type,
            &entity.name,
            &entity.properties,
            &entity.updated_at,
            &entity.scope_id.clone().unwrap_or_else(|| "NULL".to_string()),
            &entity.source_channel,
            &entity.content_hash.clone().unwrap_or_else(|| "NULL".to_string()),
            &entity.id,
        ],
    ).map_err(|e| MnemosyneError::Db(e))?;

    Ok(true)
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::NamedTempFile;

    fn create_test_db() -> NamedTempFile {
        let file = NamedTempFile::new().unwrap();
        let conn = Connection::open(file.path()).unwrap();

        // Create schema
        conn.execute(
            "CREATE TABLE entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                properties TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                scope_id TEXT,
                source_channel TEXT DEFAULT 'legacy',
                content_hash TEXT
            )",
            [],
        ).unwrap();

        conn.execute(
            "CREATE TABLE relations (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                properties TEXT,
                created_at TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                scope_id TEXT,
                source_channel TEXT DEFAULT 'legacy'
            )",
            [],
        ).unwrap();

        file
    }

    #[test]
    fn test_execute_query_basic() {
        let db = create_test_db();
        let conn = Connection::open(db.path()).unwrap();

        // Insert test data
        conn.execute(
            "INSERT INTO entities (id, type, name, properties, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ["e1", "function", "testFunc", "{}", "2024-01-01", "2024-01-01"],
        ).unwrap();

        // Test query
        let result = execute_query(
            db.path().to_str().unwrap().to_string(),
            "SELECT * FROM entities".to_string(),
            None,
        ).unwrap();

        assert_eq!(result.row_count, 1);
    }

    #[test]
    fn test_batch_insert_entities() {
        let db = create_test_db();

        let entities = vec![
            EntityInsert::new(
                "e1".to_string(),
                "function".to_string(),
                "testFunc1".to_string(),
                "{}".to_string(),
                "2024-01-01T00:00:00Z".to_string(),
                "2024-01-01T00:00:00Z".to_string(),
                1,
                None,
                "rust".to_string(),
                None,
            ),
            EntityInsert::new(
                "e2".to_string(),
                "class".to_string(),
                "TestClass".to_string(),
                "{}".to_string(),
                "2024-01-01T00:00:00Z".to_string(),
                "2024-01-01T00:00:00Z".to_string(),
                1,
                None,
                "rust".to_string(),
                None,
            ),
        ];

        let result = batch_insert_entities(db.path().to_str().unwrap().to_string(), entities).unwrap();

        assert_eq!(result.inserted, 2);
        assert_eq!(result.updated, 0);
        assert_eq!(result.failed, 0);
    }

    #[test]
    fn test_batch_insert_relations() {
        let db = create_test_db();

        // First insert entities
        let conn = Connection::open(db.path()).unwrap();
        conn.execute(
            "INSERT INTO entities (id, type, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ["e1", "entity", "Entity1", "2024-01-01", "2024-01-01"],
        ).unwrap();
        conn.execute(
            "INSERT INTO entities (id, type, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ["e2", "entity", "Entity2", "2024-01-01", "2024-01-01"],
        ).unwrap();
        drop(conn);

        // Insert relations
        let relations = vec![
            RelationInsert::new(
                "r1".to_string(),
                "e1".to_string(),
                "e2".to_string(),
                "connected_to".to_string(),
                "{}".to_string(),
                "2024-01-01T00:00:00Z".to_string(),
                1,
                None,
                "rust".to_string(),
            ),
        ];

        let result = batch_insert_relations(db.path().to_str().unwrap().to_string(), relations).unwrap();

        assert_eq!(result.inserted, 1);
        assert_eq!(result.updated, 0);
        assert_eq!(result.failed, 0);
    }

    #[test]
    fn test_batch_update_entities() {
        let db = create_test_db();

        // First insert an entity
        let conn = Connection::open(db.path()).unwrap();
        conn.execute(
            "INSERT INTO entities (id, type, name, properties, created_at, updated_at, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["e1", "function", "testFunc", "{}", "2024-01-01", "2024-01-01", "hash1"],
        ).unwrap();
        drop(conn);

        // Update with skip_unchanged = true (should skip)
        let updates = vec![
            EntityUpdate::new(
                "e1".to_string(),
                "function".to_string(),
                "testFunc".to_string(),
                "{}".to_string(),
                "2024-01-02T00:00:00Z".to_string(),
                None,
                "rust".to_string(),
                Some("hash1".to_string()),
            ),
        ];

        let result = batch_update_entities(db.path().to_str().unwrap().to_string(), updates, true).unwrap();

        assert_eq!(result.updated, 0); // Should be skipped
        assert_eq!(result.failed, 0);

        // Update with different hash (should update)
        let updates = vec![
            EntityUpdate::new(
                "e1".to_string(),
                "function".to_string(),
                "testFunc".to_string(),
                "{}".to_string(),
                "2024-01-02T00:00:00Z".to_string(),
                None,
                "rust".to_string(),
                Some("hash2".to_string()),
            ),
        ];

        let result = batch_update_entities(db.path().to_str().unwrap().to_string(), updates, true).unwrap();

        assert_eq!(result.updated, 1);
        assert_eq!(result.failed, 0);
    }
}

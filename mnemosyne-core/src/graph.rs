//! Graph operations module.
//!
//! Provides high-performance graph query operations using SQLite and petgraph.

use crate::types::{EntityQuery, GraphStats, MnemosyneError, RelationQuery};
use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::algo::dijkstra;
use pyo3::prelude::*;
use rusqlite::{Connection, params_from_iter};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ============================================================================
// Graph Query Result Types
// ============================================================================

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EntityResult {
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
}

#[pymethods]
impl EntityResult {
    #[new]
    #[pyo3(signature = (id, entity_type, name, properties, created_at, updated_at, version, scope_id=None, source_channel="legacy".to_string()))]
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
        }
    }

    fn __repr__(&self) -> String {
        format!("EntityResult(id={}, type={}, name={})", self.id, self.entity_type, self.name)
    }
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RelationResult {
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
impl RelationResult {
    #[new]
    #[pyo3(signature = (id, source_id, target_id, relation_type, properties, created_at, version, scope_id=None, source_channel="legacy".to_string()))]
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

    fn __repr__(&self) -> String {
        format!(
            "RelationResult(id={}, type={}, {} -> {})",
            self.id, self.relation_type, self.source_id, self.target_id
        )
    }
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PathResult {
    #[pyo3(get, set)]
    pub path: Vec<String>,     // Entity IDs in order
    #[pyo3(get, set)]
    pub relations: Vec<String>, // Relation types between each step
    #[pyo3(get, set)]
    pub length: usize,
}

#[pymethods]
impl PathResult {
    #[new]
    fn new(path: Vec<String>, relations: Vec<String>) -> Self {
        let length = if path.is_empty() { 0 } else { path.len() - 1 };
        Self { path, relations, length }
    }

    fn __repr__(&self) -> String {
        format!("PathResult(length={}, path={:?})", self.length, self.path)
    }
}

// ============================================================================
// Internal Helper Types
// ============================================================================

#[derive(Debug)]
struct EntityNode {
    id: String,
    entity_type: String,
    name: String,
    scope_id: Option<String>,
    source_channel: String,
}

#[derive(Debug)]
struct RelationEdge {
    id: String,
    relation_type: String,
    scope_id: Option<String>,
    source_channel: String,
}

// ============================================================================
// Graph Query Functions
// ============================================================================

/// Query entities with full-text search and filtering.
///
/// Args:
///     db_path: Path to SQLite database
///     query: EntityQuery with search term, type filter, scope filter, and limit
///
/// Returns:
///     List of EntityResult objects matching the query
#[pyfunction]
pub fn query_entities(db_path: String, query: &EntityQuery) -> PyResult<Vec<EntityResult>> {
    let conn = Connection::open(db_path)
        .map_err(|e| MnemosyneError::Db(e))?;

    let mut results = Vec::new();
    let mut sql = "SELECT e.* FROM entities e".to_string();
    let mut conditions: Vec<String> = Vec::new();
    let mut params: Vec<String> = Vec::new();

    // FTS5 search or LIKE search
    if let Some(ref term) = query.search_term {
        if fts_search_ready(&conn) {
            // Use FTS5 ranked search
            sql = "SELECT e.id, e.type, e.name, e.properties, e.created_at, e.updated_at, e.version, e.scope_id, e.source_channel
                   FROM entity_fts
                   JOIN entities e ON e.rowid = entity_fts.rowid".to_string();

            let match_expr = build_match_term(term);
            conditions.push("entity_fts MATCH ?".to_string());
            params.push(match_expr);
        } else {
            // Fallback to LIKE search
            let pattern = format!("%{}%", term);
            conditions.push("(e.name LIKE ? OR e.properties LIKE ?)".to_string());
            params.push(pattern.clone());
            params.push(pattern);
        }
    }

    // Type filter
    if let Some(ref entity_type) = query.entity_type {
        conditions.push("e.type = ?".to_string());
        params.push(entity_type.clone());
    }

    // Scope filter
    if let Some(ref scope_id) = query.scope_id {
        conditions.push("e.scope_id = ?".to_string());
        params.push(scope_id.clone());
    }

    // Combine conditions
    if !conditions.is_empty() {
        sql.push_str(" WHERE ");
        sql.push_str(&conditions.join(" AND "));
    }

    // Add ORDER BY for FTS5 ranking
    if query.search_term.is_some() && fts_search_ready(&conn) {
        sql.push_str(" ORDER BY bm25(entity_fts)");
    }

    // Add limit
    sql.push_str(&format!(" LIMIT {}", query.limit));

    // Execute query
    let mut stmt = conn.prepare(&sql)
        .map_err(|e| MnemosyneError::Db(e))?;

    let param_refs: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p as &dyn rusqlite::ToSql).collect();

    let rows = stmt.query_map(params_from_iter(param_refs.iter()), |row| {
        Ok(EntityResult {
            id: row.get("id")?,
            entity_type: row.get("type")?,
            name: row.get("name")?,
            properties: row.get::<_, Option<String>>("properties")?.unwrap_or_default(),
            created_at: row.get("created_at")?,
            updated_at: row.get("updated_at")?,
            version: row.get("version")?,
            scope_id: row.get("scope_id")?,
            source_channel: row.get::<_, Option<String>>("source_channel")?.unwrap_or_else(|| "legacy".to_string()),
        })
    })
    .map_err(|e| MnemosyneError::Db(e))?;

    for row in rows {
        results.push(row.map_err(|e| MnemosyneError::Db(e))?);
    }

    Ok(results)
}

/// Query relations with filtering.
///
/// Args:
///     db_path: Path to SQLite database
///     query: RelationQuery with source, relation, target, scope filters, and limit
///
/// Returns:
///     List of RelationResult objects matching the query
#[pyfunction]
pub fn query_relations(db_path: String, query: &RelationQuery) -> PyResult<Vec<RelationResult>> {
    let conn = Connection::open(db_path)
        .map_err(|e| MnemosyneError::Db(e))?;

    let mut results = Vec::new();
    let mut sql = "SELECT r.* FROM relations r".to_string();
    let mut conditions: Vec<String> = Vec::new();
    let mut params: Vec<String> = Vec::new();

    // Source filter
    if let Some(ref source) = query.source {
        conditions.push("r.source_id = ?".to_string());
        params.push(source.clone());
    }

    // Relation type filter
    if let Some(ref relation) = query.relation {
        conditions.push("r.relation_type = ?".to_string());
        params.push(relation.clone());
    }

    // Target filter
    if let Some(ref target) = query.target {
        conditions.push("r.target_id = ?".to_string());
        params.push(target.clone());
    }

    // Scope filter
    if let Some(ref scope_id) = query.scope_id {
        conditions.push("r.scope_id = ?".to_string());
        params.push(scope_id.clone());
    }

    // Combine conditions
    if !conditions.is_empty() {
        sql.push_str(" WHERE ");
        sql.push_str(&conditions.join(" AND "));
    }

    // Add limit
    sql.push_str(&format!(" LIMIT {}", query.limit));

    // Execute query
    let mut stmt = conn.prepare(&sql)
        .map_err(|e| MnemosyneError::Db(e))?;

    let param_refs: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p as &dyn rusqlite::ToSql).collect();

    let rows = stmt.query_map(params_from_iter(param_refs.iter()), |row| {
        Ok(RelationResult {
            id: row.get("id")?,
            source_id: row.get("source_id")?,
            target_id: row.get("target_id")?,
            relation_type: row.get("relation_type")?,
            properties: row.get::<_, Option<String>>("properties")?.unwrap_or_default(),
            created_at: row.get("created_at")?,
            version: row.get("version")?,
            scope_id: row.get("scope_id")?,
            source_channel: row.get::<_, Option<String>>("source_channel")?.unwrap_or_else(|| "legacy".to_string()),
        })
    })
    .map_err(|e| MnemosyneError::Db(e))?;

    for row in rows {
        results.push(row.map_err(|e| MnemosyneError::Db(e))?);
    }

    Ok(results)
}

/// Find shortest path between two entities.
///
/// Args:
///     db_path: Path to SQLite database
///     source_name: Name of the source entity
///     target_name: Name of the target entity
///
/// Returns:
///     PathResult with the shortest path and relations, or None if no path exists
#[pyfunction]
pub fn find_path(db_path: String, source_name: String, target_name: String) -> PyResult<Option<PathResult>> {
    let conn = Connection::open(db_path)
        .map_err(|e| MnemosyneError::Db(e))?;

    // Find entity IDs by name
    let source_id: Option<String> = conn.query_row(
        "SELECT id FROM entities WHERE name = ?",
        [&source_name],
        |row| row.get(0),
    ).ok();

    let target_id: Option<String> = conn.query_row(
        "SELECT id FROM entities WHERE name = ?",
        [&target_name],
        |row| row.get(0),
    ).ok();

    let source_id = source_id.ok_or_else(|| {
        MnemosyneError::InvalidInput(format!("Source entity not found: {}", source_name))
    })?;

    let target_id = target_id.ok_or_else(|| {
        MnemosyneError::InvalidInput(format!("Target entity not found: {}", target_name))
    })?;

    // Build graph from database
    let graph = build_graph(&conn)?;

    // Find path using petgraph
    let source_idx = find_node_index(&graph, &source_id)
        .ok_or_else(|| MnemosyneError::InvalidInput("Source node not in graph".to_string()))?;

    let target_idx = find_node_index(&graph, &target_id)
        .ok_or_else(|| MnemosyneError::InvalidInput("Target node not in graph".to_string()))?;

    // Use BFS to find shortest path
    let path_indices = bfs_path(&graph, source_idx, target_idx);

    if let Some(indices) = path_indices {
        let mut entity_ids = Vec::new();
        let mut relation_types = Vec::new();

        for i in 0..indices.len() {
            let node = &graph[indices[i]];
            entity_ids.push(node.id.clone());

            if i < indices.len() - 1 {
                if let Some(edge) = graph.find_edge(indices[i], indices[i + 1]) {
                    let edge_data = &graph[edge];
                    relation_types.push(edge_data.relation_type.clone());
                } else {
                    relation_types.push("connected_to".to_string());
                }
            }
        }

        Ok(Some(PathResult::new(entity_ids, relation_types)))
    } else {
        Ok(None)
    }
}

/// Get graph statistics.
///
/// Args:
///     db_path: Path to SQLite database
///
/// Returns:
///     GraphStats with entity count, relation count, scope count, and type distribution
#[pyfunction]
pub fn get_stats(db_path: String) -> PyResult<GraphStats> {
    let conn = Connection::open(db_path)
        .map_err(|e| MnemosyneError::Db(e))?;

    // Get entity count
    let entity_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM entities",
        [],
        |row| row.get(0),
    ).unwrap_or(0);

    // Get relation count
    let relation_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM relations",
        [],
        |row| row.get(0),
    ).unwrap_or(0);

    // Get scope count (if scopes table exists)
    let scope_count: usize = if table_exists(&conn, "scopes") {
        conn.query_row(
            "SELECT COUNT(*) FROM scopes",
            [],
            |row| row.get(0),
        ).unwrap_or(0)
    } else {
        0
    };

    // Get type counts
    let mut type_counts: HashMap<String, usize> = HashMap::new();
    let mut stmt = conn.prepare("SELECT type, COUNT(*) as count FROM entities GROUP BY type")
        .map_err(|e| MnemosyneError::Db(e))?;

    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>("type")?, row.get::<_, usize>("count")?))
    })
    .map_err(|e| MnemosyneError::Db(e))?;

    for row in rows {
        if let Ok((entity_type, count)) = row {
            type_counts.insert(entity_type, count);
        }
    }

    // Convert to JSON string
    let type_counts_json = serde_json::to_string(&type_counts)
        .map_err(|e| MnemosyneError::Json(e))?;

    Ok(GraphStats {
        entity_count,
        relation_count,
        scope_count,
        type_counts: type_counts_json,
    })
}

// ============================================================================
// Internal Helper Functions
// ============================================================================

/// Check if FTS5 search is available and ready.
fn fts_search_ready(conn: &Connection) -> bool {
    // Check if FTS5 is compiled in
    let fts5_enabled: bool = conn.query_row(
        "SELECT COUNT(*) FROM pragma_compile_options WHERE compile_options = 'ENABLE_FTS5'",
        [],
        |row| row.get(0),
    ).unwrap_or(false);

    if !fts5_enabled {
        return false;
    }

    // Check if entity_fts table exists
    table_exists(conn, "entity_fts")
}

/// Check if a table exists in the database.
fn table_exists(conn: &Connection, table_name: &str) -> bool {
    conn.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        [table_name],
        |row| row.get(0),
    ).unwrap_or(false)
}

/// Build FTS5 match term with prefix matching.
fn build_match_term(term: &str) -> String {
    if term.is_empty() {
        return term.to_string();
    }

    // If term already contains FTS5 syntax, pass through
    if term.contains(' ') || term.contains('"') || term.contains('*') ||
       term.contains('(') || term.contains(')') || term.contains(':') ||
       term.contains('+') || term.contains('-') ||
       term.contains("OR") || term.contains("AND") {
        return term.to_string();
    }

    // Add * for prefix matching
    format!("{}*", term)
}

/// Build a directed graph from the database entities and relations.
fn build_graph(conn: &Connection) -> Result<DiGraph<EntityNode, RelationEdge>, MnemosyneError> {
    let mut graph = DiGraph::new();
    let mut node_indices: HashMap<String, NodeIndex> = HashMap::new();

    // Add entities as nodes
    let mut stmt = conn.prepare(
        "SELECT id, type, name, scope_id, source_channel FROM entities"
    ).map_err(|e| MnemosyneError::Db(e))?;

    let entity_rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>("id")?,
            row.get::<_, String>("type")?,
            row.get::<_, String>("name")?,
            row.get::<_, Option<String>>("scope_id")?,
            row.get::<_, String>("source_channel")?,
        ))
    })
    .map_err(|e| MnemosyneError::Db(e))?;

    for entity_result in entity_rows {
        let (id, entity_type, name, scope_id, source_channel) = entity_result
            .map_err(|e| MnemosyneError::Db(e))?;

        let node = EntityNode {
            id: id.clone(),
            entity_type,
            name,
            scope_id,
            source_channel,
        };

        let idx = graph.add_node(node);
        node_indices.insert(id, idx);
    }

    // Add relations as edges
    let mut stmt = conn.prepare(
        "SELECT id, source_id, target_id, relation_type, scope_id, source_channel FROM relations"
    ).map_err(|e| MnemosyneError::Db(e))?;

    let relation_rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>("id")?,
            row.get::<_, String>("source_id")?,
            row.get::<_, String>("target_id")?,
            row.get::<_, String>("relation_type")?,
            row.get::<_, Option<String>>("scope_id")?,
            row.get::<_, String>("source_channel")?,
        ))
    })
    .map_err(|e| MnemosyneError::Db(e))?;

    for relation_result in relation_rows {
        let (id, source_id, target_id, relation_type, scope_id, source_channel) = relation_result
            .map_err(|e| MnemosyneError::Db(e))?;

        let source_idx = node_indices.get(&source_id);
        let target_idx = node_indices.get(&target_id);

        if let (Some(&src), Some(&tgt)) = (source_idx, target_idx) {
            let edge = RelationEdge {
                id,
                relation_type,
                scope_id,
                source_channel,
            };

            graph.add_edge(src, tgt, edge);
        }
    }

    Ok(graph)
}

/// Find node index by entity ID in the graph.
fn find_node_index(graph: &DiGraph<EntityNode, RelationEdge>, id: &str) -> Option<NodeIndex> {
    graph.node_indices().find(|&idx| &graph[idx].id == id)
}

/// Find shortest path using BFS.
fn bfs_path(
    graph: &DiGraph<EntityNode, RelationEdge>,
    start: NodeIndex,
    goal: NodeIndex,
) -> Option<Vec<NodeIndex>> {
    use std::collections::{VecDeque, HashMap};

    if start == goal {
        return Some(vec![start]);
    }

    let mut queue = VecDeque::new();
    let mut visited = HashMap::new();

    queue.push_back(start);
    visited.insert(start, None);

    while let Some(current) = queue.pop_front() {
        if current == goal {
            // Reconstruct path
            let mut path = Vec::new();
            let mut node = Some(goal);
            while let Some(n) = node {
                path.push(n);
                node = visited.get(&n).copied().flatten();
            }
            path.reverse();
            return Some(path);
        }

        for neighbor in graph.neighbors(current) {
            if !visited.contains_key(&neighbor) {
                visited.insert(neighbor, Some(current));
                queue.push_back(neighbor);
            }
        }
    }

    None
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::NamedTempFile;
    use std::io::Write;

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
                source_channel TEXT DEFAULT 'legacy'
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

        // Insert test entities
        let entities = vec![
            ("e1", "function", "authenticateUser", "{}", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", Some("s1")),
            ("e2", "class", "AuthService", "{}", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", Some("s1")),
            ("e3", "function", "validateToken", "{}", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", Some("s1")),
            ("e4", "function", "fetchUserData", "{}", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", Some("s2")),
        ];

        for e in entities {
            conn.execute(
                "INSERT INTO entities (id, type, name, properties, created_at, updated_at, scope_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                rusqlite::params![e.0, e.1, e.2, e.3, e.4, e.5, e.6],
            ).unwrap();
        }

        // Insert test relations
        conn.execute(
            "INSERT INTO relations (id, source_id, target_id, relation_type, properties, created_at, scope_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rusqlite::params!["r1", "e2", "e1", "contains", "{}", "2024-01-01T00:00:00Z", Some("s1")],
        ).unwrap();

        conn.execute(
            "INSERT INTO relations (id, source_id, target_id, relation_type, properties, created_at, scope_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rusqlite::params!["r2", "e1", "e3", "calls", "{}", "2024-01-01T00:00:00Z", Some("s1")],
        ).unwrap();

        file
    }

    #[test]
    fn test_query_entities_basic() {
        let db = create_test_db();
        let query = EntityQuery {
            search_term: None,
            entity_type: Some("function".to_string()),
            scope_id: None,
            limit: 100,
        };

        let results = query_entities(db.path().to_str().unwrap().to_string(), &query).unwrap();
        assert_eq!(results.len(), 3); // 3 functions in scope s1
    }

    #[test]
    fn test_query_relations() {
        let db = create_test_db();
        let query = RelationQuery {
            source: Some("e2".to_string()),
            relation: None,
            target: None,
            scope_id: None,
            limit: 100,
        };

        let results = query_relations(db.path().to_str().unwrap().to_string(), &query).unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].source_id, "e2");
        assert_eq!(results[0].target_id, "e1");
    }

    #[test]
    fn test_get_stats() {
        let db = create_test_db();
        let stats = get_stats(db.path().to_str().unwrap().to_string()).unwrap();
        assert_eq!(stats.entity_count, 4);
        assert_eq!(stats.relation_count, 2);

        let type_counts: HashMap<String, usize> = serde_json::from_str(&stats.type_counts).unwrap();
        assert_eq!(type_counts.get("function"), Some(&3));
        assert_eq!(type_counts.get("class"), Some(&1));
    }

    #[test]
    fn test_find_path() {
        let db = create_test_db();
        let result = find_path(
            db.path().to_str().unwrap().to_string(),
            "AuthService".to_string(),
            "validateToken".to_string(),
        ).unwrap();

        assert!(result.is_some());
        let path = result.unwrap();
        assert_eq!(path.length, 2);
        assert_eq!(path.path, vec!["e2", "e1", "e3"]);
        assert_eq!(path.relations, vec!["contains", "calls"]);
    }
}

//! Mnemosyne Core - High-performance knowledge graph operations.
//!
//! This module provides PyO3 bindings for fast wiki generation, graph queries,
//! and database operations.

use pyo3::prelude::*;

// Public modules
pub mod types;
pub mod wiki;

// Public graph module with exported types
pub mod graph;
pub use graph::{EntityResult, RelationResult, PathResult};

// Public database module with exported types
pub mod db;
pub use db::{EntityInsert, RelationInsert, EntityUpdate};

/// Mnemosyne Core Python module.
#[pymodule]
fn mnemosyne_core(_py: Python, m: &PyModule) -> PyResult<()> {
    // Register types
    m.add_class::<types::WikiUpdate>()?;
    m.add_class::<types::EntityData>()?;
    m.add_class::<types::RelationData>()?;
    m.add_class::<types::SourceData>()?;
    m.add_class::<types::SourcePageData>()?;
    m.add_class::<types::IndexOptions>()?;
    m.add_class::<types::EntityQuery>()?;
    m.add_class::<types::RelationQuery>()?;
    m.add_class::<types::GraphStats>()?;
    m.add_class::<types::QueryResult>()?;
    m.add_class::<types::BatchResult>()?;

    // Register graph types
    m.add_class::<graph::EntityResult>()?;
    m.add_class::<graph::RelationResult>()?;
    m.add_class::<graph::PathResult>()?;

    // Register database types
    m.add_class::<db::EntityInsert>()?;
    m.add_class::<db::RelationInsert>()?;
    m.add_class::<db::EntityUpdate>()?;

    // Register wiki functions
    m.add_function(wrap_pyfunction!(wiki::glob_markdown, m)?)?;
    m.add_function(wrap_pyfunction!(wiki::rebuild_index, m)?)?;
    m.add_function(wrap_pyfunction!(wiki::write_entity_page, m)?)?;
    m.add_function(wrap_pyfunction!(wiki::write_source_page, m)?)?;

    // Register graph functions
    m.add_function(wrap_pyfunction!(graph::query_entities, m)?)?;
    m.add_function(wrap_pyfunction!(graph::query_relations, m)?)?;
    m.add_function(wrap_pyfunction!(graph::find_path, m)?)?;
    m.add_function(wrap_pyfunction!(graph::get_stats, m)?)?;

    // Register database functions
    m.add_function(wrap_pyfunction!(db::execute_query, m)?)?;
    m.add_function(wrap_pyfunction!(db::batch_insert_entities, m)?)?;
    m.add_function(wrap_pyfunction!(db::batch_insert_relations, m)?)?;
    m.add_function(wrap_pyfunction!(db::batch_update_entities, m)?)?;

    Ok(())
}

//! Wiki generation module.
//!
//! Provides fast wiki page generation with parallel processing.

use crate::types::{EntityData, IndexOptions, RelationData, SourceData, SourcePageData, WikiUpdate};
use chrono::Utc;
use pyo3::prelude::*;
use rayon::prelude::*;
use std::fs;
use std::path::{Path, PathBuf};
use walkdir::WalkDir;

#[cfg(test)]
mod tests;

const GENERATED_START: &str = "<!-- MNEMOSYNE:GENERATED:START -->";
const GENERATED_END: &str = "<!-- MNEMOSYNE:GENERATED:END -->";

const EDITOR_GUIDANCE: &[&str] = &[
    "## Editing guidance",
    "",
    "- This generated section is replaced by `mnemosyne add`, `mnemosyne update`, and `mnemosyne wiki rebuild`.",
    "- Add human notes outside the `MNEMOSYNE:GENERATED` markers, preferably under `## Notes`.",
    "- Raw sources plus the graph database remain authoritative; editor pages are readable views plus manual notes.",
];

// ============================================================================
// Public API
// ============================================================================

/// Find all markdown files in a directory.
#[pyfunction]
pub fn glob_markdown(dir_path: &str, recursive: bool) -> PyResult<Vec<String>> {
    let path = Path::new(dir_path);
    if !path.exists() || !path.is_dir() {
        return Ok(Vec::new());
    }

    let mut files = Vec::new();

    if recursive {
        let walker = WalkDir::new(path)
            .into_iter()
            .filter_map(|e| e.ok())
            .filter(|e| {
                e.file_type().is_file()
                    && e.path().extension().map_or(false, |ext| ext == "md")
            });

        for entry in walker {
            files.push(entry.path().to_string_lossy().into_owned());
        }
    } else {
        // Non-recursive: only immediate children
        if let Ok(entries) = fs::read_dir(path) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_file()
                    && path.extension().map_or(false, |ext| ext == "md")
                {
                    files.push(path.to_string_lossy().into_owned());
                }
            }
        }
    }

    Ok(files)
}

/// Generate index.md content.
#[pyfunction]
pub fn rebuild_index(
    wiki_root: &str,
    entity_pages: Vec<String>,
    source_pages: Vec<String>,
    options: &IndexOptions,
) -> PyResult<String> {
    let wiki_root_path = Path::new(wiki_root);

    // Helper to format wiki links
    let format_link = |p: &str| -> String {
        let abs = Path::new(p);
        if let Ok(rel) = abs.strip_prefix(wiki_root_path) {
            let rel_str = rel.to_string_lossy().replace("\\", "/");
            let name = rel.file_stem().map_or("", |s| s.to_str().unwrap_or(""));
            format!("[[{}]](file://{})", name, rel_str)
        } else {
            format!("[[{}]]", p)
        }
    };

    // Parallel formatting using Rayon
    let entity_links: Vec<String> = entity_pages
        .par_iter()
        .map(|p| format!("- {}", format_link(p)))
        .collect();

    let source_links: Vec<String> = source_pages
        .par_iter()
        .map(|p| format!("- {}", format_link(p)))
        .collect();

    // Build index content
    let mut lines = Vec::new();

    // Frontmatter
    lines.push(format!(
        "---\npage_type: index\nupdated_at: {}\n---\n",
        options.updated_at
    ));

    // Header
    lines.push("# Mnemosyne LLM Wiki Index\n".to_string());
    lines.push(format!("{}\n", GENERATED_START));

    // Editor guidance
    for line in &options.editor_guidance {
        lines.push(format!("{}\n", line));
    }
    lines.push("\n".to_string());
    lines.push(format!("Last updated: {}\n\n", options.updated_at));

    // Entity pages
    lines.push("## Entity pages\n\n".to_string());
    if entity_links.is_empty() {
        lines.push("- _No entity pages yet._\n".to_string());
    } else {
        lines.push(entity_links.join("\n"));
        lines.push("\n".to_string());
    }

    // Source pages
    lines.push("\n## Source pages\n\n".to_string());
    if source_links.is_empty() {
        lines.push("- _No source pages yet._\n".to_string());
    } else {
        lines.push(source_links.join("\n"));
        lines.push("\n".to_string());
    }

    // Maintenance section
    lines.push("\n## Maintenance\n\n".to_string());

    if options.include_log_link {
        lines.push("- [[log]] records ingest chronology.\n".to_string());
    } else {
        lines.push("- Log page is created on first ingest event.\n".to_string());
    }

    lines.push("- Knowledge graph queries remain available through `mnemosyne query`.\n".to_string());
    lines.push("- Raw sources remain outside this wiki and should be treated as source of truth.\n\n".to_string());
    lines.push(format!("{}\n", GENERATED_END));

    Ok(lines.concat())
}

/// Write a single entity wiki page.
#[pyfunction]
pub fn write_entity_page(
    wiki_root: &str,
    entity: &EntityData,
    relations: Vec<RelationData>,
    sources: Vec<SourceData>,
) -> PyResult<String> {
    let wiki_path = entity_page_path(wiki_root, &entity.entity_type, &entity.label);
    let wiki_path_buf = Path::new(&wiki_path);

    // Create parent directory if needed
    if let Some(parent) = wiki_path_buf.parent() {
        fs::create_dir_all(parent)?;
    }

    // Read existing content to preserve manual notes
    let existing_content = if wiki_path_buf.exists() {
        fs::read_to_string(&wiki_path).unwrap_or_default()
    } else {
        String::new()
    };

    // Extract manual notes (outside generated markers)
    let manual_notes = extract_manual_notes(&existing_content);

    // Build page content
    let mut content = String::new();

    // Frontmatter
    content.push_str(&format!(
        "---\npage_type: entity\nentity_id: {}\nentity_type: {}\nlabel: {}\nscope_id: {}\nsource_channel: {}\nupdated_at: {}\n---\n\n",
        entity.id,
        entity.entity_type,
        entity.label,
        entity.scope_id,
        entity.source_channel,
        Utc::now().to_rfc3339()
    ));

    // Title
    content.push_str(&format!("# {}\n\n", entity.label));

    // Generated section
    content.push_str(GENERATED_START);
    content.push_str("\n\n");

    // Type badge
    content.push_str(&format!("**Type**: `{}`\n\n", entity.entity_type));

    // Sources section
    content.push_str("## Sources\n\n");
    if sources.is_empty() {
        content.push_str("- _No sources._\n");
    } else {
        for source in &sources {
            content.push_str(&format!("- {} ({})\n", source.source_id, source.source_file));
        }
    }
    content.push_str("\n");

    // Relations section
    content.push_str("## Relations\n\n");
    if relations.is_empty() {
        content.push_str("- _No relations._\n");
    } else {
        for rel in &relations {
            content.push_str(&format!(
                "- {} → {} → {}\n",
                rel.source, rel.relation, rel.target
            ));
        }
    }
    content.push_str("\n");

    // Properties section (if any)
    if let Ok(props) = serde_json::from_str::<serde_json::Value>(&entity.properties) {
        if props.as_object().map_or(false, |o| !o.is_empty()) {
            content.push_str("## Properties\n\n");
            content.push_str("```json\n");
            content.push_str(&serde_json::to_string_pretty(&props).unwrap_or_default());
            content.push_str("\n```\n\n");
        }
    }

    content.push_str(GENERATED_END);
    content.push_str("\n\n");

    // Manual notes section
    content.push_str("## Notes\n\n");
    content.push_str(&manual_notes);

    // Atomic write
    write_atomic(&wiki_path, &content)?;

    Ok(wiki_path)
}

/// Write a single source page.
#[pyfunction]
pub fn write_source_page(
    wiki_root: &str,
    source: &SourcePageData,
    entities: Vec<EntityData>,
    relations: Vec<RelationData>,
) -> PyResult<String> {
    let wiki_path = source_page_path(wiki_root, &source.domain, &source.source);
    let wiki_path_buf = Path::new(&wiki_path);

    // Create parent directory if needed
    if let Some(parent) = wiki_path_buf.parent() {
        fs::create_dir_all(parent)?;
    }

    // Build page content
    let mut content = String::new();

    // Frontmatter
    content.push_str(&format!(
        "---\npage_type: source\ndomain: {}\nsource_id: {}\nsource: {}\noriginal_source: {}\nraw_path: {}\ncontent_hash: {}\nscope_id: {}\nsource_channel: {}\nupdated_at: {}\n---\n\n",
        source.domain,
        source.source,
        source.source,
        source.original_source,
        source.raw_path,
        source.content_hash,
        source.scope_id,
        source.source_channel,
        Utc::now().to_rfc3339()
    ));

    // Title
    let title = source
        .source
        .split('/')
        .last()
        .unwrap_or(&source.source)
        .to_string();
    content.push_str(&format!("# {}\n\n", title));

    // Generated section
    content.push_str(GENERATED_START);
    content.push_str("\n\n");

    // Metadata
    content.push_str("## Metadata\n\n");
    content.push_str(&format!("- **Domain**: {}\n", source.domain));
    content.push_str(&format!("- **Source ID**: `{}`\n", source.source));
    content.push_str(&format!("- **Original source**: `{}`\n", source.original_source));
    if !source.raw_path.is_empty() {
        content.push_str(&format!("- **Raw path**: `{}`\n", source.raw_path));
    }
    if !source.content_hash.is_empty() {
        content.push_str(&format!("- **Content hash**: `{}`\n", source.content_hash));
    }
    content.push_str(&format!("- **Scope**: {}\n", source.scope_id));
    content.push_str(&format!("- **Source channel**: {}\n\n", source.source_channel));

    // Extracted entities
    content.push_str("## Extracted entities\n\n");
    if entities.is_empty() {
        content.push_str("- _No entities extracted._\n");
    } else {
        for entity in &entities {
            content.push_str(&format!(
                "- {} — `{}`\n",
                entity.label, entity.entity_type
            ));
        }
    }
    content.push_str("\n");

    // Extracted relations
    content.push_str("## Extracted relations\n\n");
    if relations.is_empty() {
        content.push_str("- _No relations extracted._\n");
    } else {
        for rel in &relations {
            content.push_str(&format!(
                "- {} → {} → {}\n",
                rel.source, rel.relation, rel.target
            ));
        }
    }
    content.push_str("\n");

    // Source excerpt placeholder
    content.push_str("## Source excerpt\n\n");
    content.push_str("_Omitted by default. Use `--wiki-excerpts` to opt in._\n\n");

    content.push_str(GENERATED_END);
    content.push_str("\n\n");

    // Manual notes section
    content.push_str("## Notes\n\n");

    // Atomic write
    write_atomic(&wiki_path, &content)?;

    Ok(wiki_path)
}

// ============================================================================
// Helper Functions
// ============================================================================

fn entity_page_path(wiki_root: &str, entity_type: &str, label: &str) -> String {
    let sanitized_label = sanitize_filename(label);
    Path::new(wiki_root)
        .join("entities")
        .join(sanitize_type(entity_type))
        .join(format!("{}.md", sanitized_label))
        .to_string_lossy()
        .into_owned()
}

fn source_page_path(wiki_root: &str, domain: &str, source: &str) -> String {
    let sanitized_source = sanitize_filename(source);
    Path::new(wiki_root)
        .join("sources")
        .join(domain)
        .join(format!("{}.md", sanitized_source))
        .to_string_lossy()
        .into_owned()
}

pub fn sanitize_filename(name: &str) -> String {
    name.chars()
        .map(|c| match c {
            '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*' => '_',
            c if c.is_control() => '_',
            c => c,
        })
        .collect::<String>()
        .trim()
        .to_string()
}

pub fn sanitize_type(t: &str) -> String {
    t.chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '_' || c == '-' {
            c
        } else {
            '_'
        })
        .collect()
}

fn extract_manual_notes(content: &str) -> String {
    // Find the manual notes section (after GENERATED_END)
    if let Some(pos) = content.find(GENERATED_END) {
        let after_generated = &content[pos + GENERATED_END.len()..];
        if let Some(notes_pos) = after_generated.find("## Notes") {
            return after_generated[notes_pos + "## Notes".len()..].trim().to_string() + "\n";
        }
    }
    String::new()
}

fn write_atomic(path: &str, content: &str) -> std::io::Result<()> {
    let path_buf = Path::new(path);
    let temp_path = path_buf.with_extension("tmp");

    fs::write(&temp_path, content)?;
    fs::rename(&temp_path, path_buf)?;

    Ok(())
}

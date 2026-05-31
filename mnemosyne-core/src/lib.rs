use pyo3::prelude::*;
use rayon::prelude::*;
use std::path::Path;
use walkdir::WalkDir;

/// Fast directory traversal to find Markdown files.
#[pyfunction]
fn fast_glob_markdown(dir_path: &str) -> PyResult<Vec<String>> {
    let path = Path::new(dir_path);
    if !path.exists() || !path.is_dir() {
        return Ok(Vec::new());
    }

    let files: Vec<String> = WalkDir::new(path)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_file() && e.path().extension().map_or(false, |ext| ext == "md"))
        .map(|e| e.path().to_string_lossy().into_owned())
        .collect();

    Ok(files)
}

/// Fast generated index.md content constructor.
#[pyfunction]
fn fast_rebuild_index(
    wiki_root: &str,
    entity_pages: Vec<String>,
    source_pages: Vec<String>,
    updated_at: &str,
    editor_guidance: Vec<String>,
) -> PyResult<String> {
    let wiki_root_path = Path::new(wiki_root);

    // Helper function to turn absolute path to relative wiki link
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

    let mut lines = Vec::new();
    lines.push(format!("---\npage_type: index\nupdated_at: {}\n---\n", updated_at));
    lines.push("# Mnemosyne LLM Wiki Index\n".to_string());
    lines.push("<!-- MNEMOSYNE:GENERATED:START -->\n".to_string());

    for line in editor_guidance {
        lines.push(format!("{}\n", line));
    }
    lines.push("\n".to_string());
    lines.push(format!("Last updated: {}\n\n", updated_at));
    lines.push("## Entity pages\n\n".to_string());

    if entity_links.is_empty() {
        lines.push("- _No entity pages yet._\n".to_string());
    } else {
        lines.push(entity_links.join("\n") + "\n");
    }

    lines.push("\n## Source pages\n\n".to_string());
    if source_links.is_empty() {
        lines.push("- _No source pages yet._\n".to_string());
    } else {
        lines.push(source_links.join("\n") + "\n");
    }

    lines.push("\n## Maintenance\n\n".to_string());
    
    // Check if log.md exists
    let log_path = wiki_root_path.join("log.md");
    if log_path.exists() {
        lines.push("- [[log]] records ingest chronology.\n".to_string());
    } else {
        lines.push("- Log page is created on first ingest event.\n".to_string());
    }
    
    lines.push("- Knowledge graph queries remain available through `mnemosyne query`.\n".to_string());
    lines.push("- Raw sources remain outside this wiki and should be treated as source of truth.\n\n".to_string());
    lines.push("<!-- MNEMOSYNE:GENERATED:END -->\n".to_string());

    Ok(lines.concat())
}

/// A Python module implemented in Rust.
#[pymodule]
fn mnemosyne_core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(fast_glob_markdown, m)?)?;
    m.add_function(wrap_pyfunction!(fast_rebuild_index, m)?)?;
    Ok(())
}

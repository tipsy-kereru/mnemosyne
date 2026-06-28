//! Unit tests for wiki module.
//!
//! These tests test wiki functions without PyO3 dependencies.

use super::*;
use tempfile::TempDir;

#[test]
fn test_glob_markdown_empty() {
    let temp = TempDir::new().unwrap();
    let result = glob_markdown(temp.path().to_str().unwrap(), true);
    assert!(result.is_ok());
    assert!(result.unwrap().is_empty());
}

#[test]
fn test_glob_markdown_non_recursive() {
    let temp = TempDir::new().unwrap();
    let temp_path = temp.path();

    // Create a markdown file
    std::fs::write(temp_path.join("test.md"), "# Test\n").unwrap();

    // Create a subdirectory with a markdown file
    std::fs::create_dir(temp_path.join("subdir")).unwrap();
    std::fs::write(temp_path.join("subdir/nested.md"), "# Nested\n").unwrap();

    // Non-recursive should only find the top-level file
    let result = glob_markdown(temp_path.to_str().unwrap(), false).unwrap();
    assert_eq!(result.len(), 1);
    assert!(result[0].ends_with("test.md"));
}

#[test]
fn test_glob_markdown_recursive() {
    let temp = TempDir::new().unwrap();
    let temp_path = temp.path();

    // Create markdown files
    std::fs::write(temp_path.join("test.md"), "# Test\n").unwrap();
    std::fs::create_dir(temp_path.join("subdir")).unwrap();
    std::fs::write(temp_path.join("subdir/nested.md"), "# Nested\n").unwrap();

    // Recursive should find both files
    let result = glob_markdown(temp_path.to_str().unwrap(), true).unwrap();
    assert_eq!(result.len(), 2);
}

#[test]
fn test_sanitize_filename() {
    // Test various problematic characters
    let inputs = vec![
        ("normal_name", "normal_name"),
        ("name/with/slashes", "name_with_slashes"),
        ("name:with:colons", "name_with_colons"),
        ("name<>with|special?chars*", "name__with_special_chars_"),
    ];

    for (input, expected) in inputs {
        let result = sanitize_filename(input);
        assert_eq!(result, expected, "Failed for input: {}", input);
    }
}

#[test]
fn test_sanitize_type() {
    // Test type sanitization
    let inputs = vec![
        ("function", "function"),
        ("test-type", "test_type"),
        ("test type", "test_type"),
        ("test:type", "test_type"),
    ];

    for (input, expected) in inputs {
        let result = sanitize_type(input);
        assert_eq!(result, expected, "Failed for input: {}", input);
    }
}

#[test]
fn test_file_operations() {
    let temp = TempDir::new().unwrap();
    let test_file = temp.path().join("test.md");

    let content = "# Test Content\n\nThis is a test.";

    // Test basic file operations work
    std::fs::write(&test_file, content).unwrap();
    let read_content = std::fs::read_to_string(&test_file).unwrap();
    assert_eq!(read_content, content);
}

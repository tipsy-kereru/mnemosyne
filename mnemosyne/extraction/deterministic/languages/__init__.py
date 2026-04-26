"""
Language-specific AST extractors (SPEC-TS-001).

Each language module provides an extractor that uses tree-sitter queries to
pull entities, imports, and call-graph edges from source files.
"""

from mnemosyne.extraction.deterministic.languages.python_extractor import PythonExtractor

__all__ = [
    "PythonExtractor",
]

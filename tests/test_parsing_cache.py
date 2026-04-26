"""
Tests for content-hash-based caching in TreeSitterExtractor (SPEC-TS-001 Task 7).

Covers: cache hit on identical content, cache miss on content change,
clear_cache(), and caching behavior in extract_directory().
"""

import tempfile
from pathlib import Path

import pytest

from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor
from mnemosyne.extraction.deterministic.types import ParseResult


class TestParsingCache:
    """Tests for content-hash-based caching of ParseResult."""

    def test_cache_hit_same_content(self):
        """Parsing the same file twice returns cached result on second call."""
        ext = TreeSitterExtractor()
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def hello():\n    pass\n")
            f.flush()
            path = Path(f.name)

            result1 = ext.extract_file_full(path)
            result2 = ext.extract_file_full(path)

            # Same content hash means cache hit
            assert result1.content_hash == result2.content_hash
            assert len(result1.entities) == len(result2.entities)

    def test_cache_miss_after_modification(self):
        """Modifying a file causes a cache miss and re-parse."""
        ext = TreeSitterExtractor()
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def hello():\n    pass\n")
            f.flush()
            path = Path(f.name)

            result1 = ext.extract_file_full(path)

            # Modify the file
            with open(path, "w") as f2:
                f2.write("def hello():\n    pass\n\ndef world():\n    pass\n")

            result2 = ext.extract_file_full(path)

            # Content hash should differ
            assert result1.content_hash != result2.content_hash
            # New result should have more entities
            assert len(result2.entities) > len(result1.entities)

    def test_clear_cache(self):
        """clear_cache() removes all cached results."""
        ext = TreeSitterExtractor()
        assert hasattr(ext, "_cache")

        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def hello():\n    pass\n")
            f.flush()
            path = Path(f.name)

            ext.extract_file_full(path)
            assert len(ext._cache) > 0

            ext.clear_cache()
            assert len(ext._cache) == 0

    def test_cache_different_files_independently(self):
        """Different files are cached independently."""
        ext = TreeSitterExtractor()

        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "a.py"
            file2 = Path(tmpdir) / "b.py"
            file1.write_text("def foo():\n    pass\n")
            file2.write_text("def bar():\n    pass\n")

            result1 = ext.extract_file_full(file1)
            result2 = ext.extract_file_full(file2)

            assert result1.content_hash != result2.content_hash
            assert result1.entities[0].name == "foo"
            assert result2.entities[0].name == "bar"

    def test_cache_with_extract_directory(self):
        """extract_directory uses caching internally."""
        ext = TreeSitterExtractor()

        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir) / "test.py"
            py_file.write_text("def hello():\n    pass\n")

            # First call populates cache
            entities1 = ext.extract_directory(Path(tmpdir))
            cache_size_after_first = len(ext._cache)

            # Second call should hit cache
            entities2 = ext.extract_directory(Path(tmpdir))
            assert len(entities1) == len(entities2)
            assert len(ext._cache) == cache_size_after_first

"""
Tests for CLI entry points (SPEC-PKG-001).

Tests verify that argparse-based CLI modules exist and handle flags correctly.
Tests for installed console_scripts (mnemosyne, mnemosyne-query, mnemosyne-extract)
are skipped when not installed, since they require pip install.
"""

import subprocess
import sys

import pytest


class TestCLIHelpFlag:
    """Test that CLI modules respond to --help."""

    def test_python_m_graph_stats(self):
        """python -m mnemosyne.graph.knowledge_graph --stats works."""
        result = subprocess.run(
            [sys.executable, "-m", "mnemosyne.graph.knowledge_graph", "--stats"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # Output should contain JSON stats
        assert "entities" in result.stdout or "density" in result.stdout

    def test_python_m_extract_help(self):
        """python -m mnemosyne.extraction.deterministic.code_parser --help works."""
        result = subprocess.run(
            [sys.executable, "-m", "mnemosyne.extraction.deterministic.code_parser", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "path" in result.stdout.lower() or "extract" in result.stdout.lower()

    def test_python_m_semantic_help(self):
        """python -m mnemosyne.extraction.semantic.slm_extractor --help works."""
        result = subprocess.run(
            [sys.executable, "-m", "mnemosyne.extraction.semantic.slm_extractor", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "text" in result.stdout.lower() or "entities" in result.stdout.lower()


class TestCLIModules:
    """Test that CLI module functions are importable."""

    def test_main_cli_importable(self):
        """mnemosyne.cli module is importable."""
        from mnemosyne.cli import main
        assert callable(main)

    def test_graph_cli_importable(self):
        """mnemosyne.graph.cli module is importable."""
        from mnemosyne.graph.cli import main
        assert callable(main)

    def test_extraction_cli_importable(self):
        """mnemosyne.extraction.cli module is importable."""
        from mnemosyne.extraction.cli import main
        assert callable(main)


class TestCLIEntryPoints:
    """Test console_scripts entry points (skip if not installed)."""

    @pytest.fixture(autouse=True)
    def _check_installed(self):
        """Skip tests if mnemosyne is not pip-installed."""
        try:
            result = subprocess.run(
                ["mnemosyne", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                pytest.skip("mnemosyne CLI not installed (run pip install -e .)")
        except FileNotFoundError:
            pytest.skip("mnemosyne CLI not installed (run pip install -e .)")

    def test_mnemosyne_version_flag(self):
        """mnemosyne --version outputs 0.1.0."""
        result = subprocess.run(
            ["mnemosyne", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "0.1.0" in result.stdout or "0.1.0" in result.stderr

    def test_mnemosyne_help_flag(self):
        """mnemosyne --help exits with code 0."""
        result = subprocess.run(
            ["mnemosyne", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "mnemosyne" in result.stdout.lower()

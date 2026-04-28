"""Tests for __main__.py entry point (SPEC-PROD-002, REQ-005).

Verifies that `python -m mnemosyne` invokes the CLI correctly.
"""

import subprocess
import sys



class TestMainEntryPoint:
    def test_python_m_mnemosyne_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "mnemosyne", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "mnemosyne" in result.stdout.lower()

    def test_python_m_mnemosyne_query_stats(self):
        """python -m mnemosyne query --stats should work."""
        result = subprocess.run(
            [sys.executable, "-m", "mnemosyne", "query", "--stats"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

    def test_main_imports_cli_main(self):
        from mnemosyne.__main__ import main
        assert callable(main)

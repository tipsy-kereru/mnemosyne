"""
Tests for CLI entry points (SPEC-PKG-001, REQ-003 of SPEC-PROD-001).

Tests verify that argparse-based CLI modules handle flags, subcommand dispatch,
and error conditions correctly. Graph CLI tests use mocks to avoid real DB I/O.
"""

import json
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Existing tests: CLI help flags and subprocess-based integration tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# mnemosyne/cli.py tests (REQ-003)
# ---------------------------------------------------------------------------


class TestMainCLIVersion:
    """Test --version flag for the main mnemosyne CLI."""

    def test_version_flag_outputs_version_string(self, capsys):
        """--version prints the version and exits with SystemExit."""
        from mnemosyne.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "0.1.0" in captured.out or "0.1.0" in captured.err

    def test_version_flag_exit_code_zero(self):
        """--version exits with code 0 (argparse convention)."""
        from mnemosyne.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])

        assert exc_info.value.code == 0


class TestMainCLIHelp:
    """Test --help flag for the main mnemosyne CLI."""

    def test_help_flag_outputs_usage(self, capsys):
        """--help prints usage information and exits."""
        from mnemosyne.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "mnemosyne" in captured.out.lower()
        assert "usage" in captured.out.lower()

    def test_help_flag_shows_subcommands(self, capsys):
        """--help output includes subcommand names."""
        from mnemosyne.cli import main

        with pytest.raises(SystemExit):
            main(["--help"])

        captured = capsys.readouterr()
        assert "query" in captured.out
        assert "extract" in captured.out


class TestMainCLINoArgs:
    """Test behavior when no subcommand is given."""

    def test_no_args_prints_help(self, capsys):
        """Running with no args prints help text (does not crash)."""
        from mnemosyne.cli import main

        main([])
        captured = capsys.readouterr()
        assert "mnemosyne" in captured.out.lower() or "usage" in captured.out.lower()


class TestMainCLISubcommandDispatch:
    """Test subcommand routing to correct module."""

    def test_query_dispatch_calls_graph_main(self):
        """'query' subcommand delegates to graph.cli.main."""
        from mnemosyne.cli import main

        mock_fn = MagicMock()
        with patch("mnemosyne.graph.cli.main", mock_fn):
            main(["query", "--query", "entity:function[parse_config]"])

        mock_fn.assert_called_once()

    def test_extract_dispatch_calls_extract_main(self):
        """'extract' subcommand delegates to extraction.cli.main."""
        from mnemosyne.cli import main

        mock_fn = MagicMock()
        with patch("mnemosyne.extraction.cli.main", mock_fn):
            main(["extract", "/tmp/project", "--domain", "coding", "--format", "json"])

        mock_fn.assert_called_once()

    def test_query_stats_flag_routed(self):
        """'query --stats' passes --stats flag to graph CLI."""
        from mnemosyne.cli import _build_query_argv

        args = MagicMock(stats=True, query=None)
        argv = _build_query_argv(args)
        assert "--stats" in argv

    def test_query_query_string_routed(self):
        """'query --query X' passes query string to graph CLI."""
        from mnemosyne.cli import _build_query_argv

        args = MagicMock(stats=False, query="entity:function[foo]")
        argv = _build_query_argv(args)
        assert "--query" in argv
        assert "entity:function[foo]" in argv

    def test_query_both_flags_routed(self):
        """'query --stats --query X' passes both flags."""
        from mnemosyne.cli import _build_query_argv

        args = MagicMock(stats=True, query="search:auth")
        argv = _build_query_argv(args)
        assert "--stats" in argv
        assert "--query" in argv
        assert "search:auth" in argv


class TestMainCLIExtractArgv:
    """Test _build_extract_argv helper."""

    def test_builds_correct_argv(self):
        """_build_extract_argv assembles path, domain, format correctly."""
        from mnemosyne.cli import _build_extract_argv

        args = MagicMock(
            path="/tmp/project", domain="coding", format="wiki",
            scope_id=None, source_channel="cli",
        )
        argv = _build_extract_argv(args)
        assert argv == ["/tmp/project", "--domain", "coding", "--format", "wiki"]

    def test_builds_json_format(self):
        """_build_extract_argv handles json format."""
        from mnemosyne.cli import _build_extract_argv

        args = MagicMock(
            path="/tmp/project", domain="daily", format="json",
            scope_id=None, source_channel="cli",
        )
        argv = _build_extract_argv(args)
        assert "--format" in argv
        assert "json" in argv


class TestMainCLIInvalidArgs:
    """Test error handling for invalid arguments."""

    def test_invalid_flag_exits_with_error(self):
        """Unknown flag causes SystemExit with non-zero code."""
        from mnemosyne.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--nonexistent-flag"])

        assert exc_info.value.code != 0

    def test_invalid_subcommand_exits_with_error(self):
        """Unknown subcommand causes SystemExit with non-zero code."""
        from mnemosyne.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["bogus-subcommand"])

        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# mnemosyne/graph/cli.py tests (REQ-003)
# ---------------------------------------------------------------------------


class TestGraphCLIHelp:
    """Test --help flag for graph CLI."""

    def test_help_flag_outputs_usage(self, capsys):
        """--help prints usage information and exits."""
        from mnemosyne.graph.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "mnemosyne-query" in captured.out or "query" in captured.out.lower()


class TestGraphCLIQuery:
    """Test --query flag for graph CLI."""

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_valid_query_prints_json_result(self, mock_kg_class, capsys):
        """--query with a valid query string prints JSON output."""
        mock_kg = MagicMock()
        mock_kg.query.return_value = {
            "results": [{"name": "parse_config", "type": "function"}],
        }
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        main(["--query", "entity:function[parse_config]"])

        captured = capsys.readouterr()
        assert "parse_config" in captured.out
        assert "function" in captured.out
        mock_kg.query.assert_called_once_with("entity:function[parse_config]")
        mock_kg.close.assert_called_once()

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_query_with_session_scope(self, mock_kg_class, capsys):
        """--query with @session modifier passes the full query string."""
        mock_kg = MagicMock()
        mock_kg.query.return_value = {"results": []}
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        main(["--query", "entity:task[*]@session:impl-session"])

        mock_kg.query.assert_called_once_with("entity:task[*]@session:impl-session")
        mock_kg.close.assert_called_once()

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_query_with_project_scope(self, mock_kg_class, capsys):
        """--query with @project modifier passes the full query string."""
        mock_kg = MagicMock()
        mock_kg.query.return_value = {"results": []}
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        main(["--query", "entity:task[*]@project:snake-game"])

        mock_kg.query.assert_called_once_with("entity:task[*]@project:snake-game")
        mock_kg.close.assert_called_once()

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_query_with_combined_scope_modifiers(self, mock_kg_class):
        """--query with multiple @ modifiers preserves the full string."""
        mock_kg = MagicMock()
        mock_kg.query.return_value = {"results": []}
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        main(["--query", "relation:calls@session:s1@channel:code"])

        mock_kg.query.assert_called_once_with("relation:calls@session:s1@channel:code")

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_query_result_is_valid_json(self, mock_kg_class, capsys):
        """--query output is valid JSON."""
        mock_kg = MagicMock()
        mock_kg.query.return_value = {"count": 1, "results": [{"id": 42}]}
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        main(["--query", "search:auth"])

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["count"] == 1

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_query_closes_kg_on_success(self, mock_kg_class):
        """KnowledgeGraph.close() is called after successful query."""
        mock_kg = MagicMock()
        mock_kg.query.return_value = {}
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        main(["--query", "entity:function[foo]"])

        mock_kg.close.assert_called_once()

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_query_closes_kg_on_error(self, mock_kg_class):
        """KnowledgeGraph.close() is called even when query raises."""
        mock_kg = MagicMock()
        mock_kg.query.side_effect = RuntimeError("DB error")
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        with pytest.raises(RuntimeError, match="DB error"):
            main(["--query", "entity:function[foo]"])

        mock_kg.close.assert_called_once()


class TestGraphCLIStats:
    """Test --stats flag for graph CLI."""

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_stats_empty_database(self, mock_kg_class, capsys):
        """--stats with empty database shows zero counts."""
        mock_kg = MagicMock()
        mock_kg.get_stats.return_value = {
            "entities": 0,
            "relations": 0,
            "by_type": {},
            "density": 0.0,
            "connected_components": 0,
        }
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        main(["--stats"])

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["entities"] == 0
        assert parsed["relations"] == 0
        mock_kg.get_stats.assert_called_once()
        mock_kg.close.assert_called_once()

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_stats_populated_database(self, mock_kg_class, capsys):
        """--stats with populated database shows correct counts."""
        mock_kg = MagicMock()
        mock_kg.get_stats.return_value = {
            "entities": 42,
            "relations": 18,
            "by_type": {"function": 25, "class": 10, "module": 7},
            "density": 0.21,
            "connected_components": 3,
        }
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        main(["--stats"])

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["entities"] == 42
        assert parsed["relations"] == 18
        assert parsed["by_type"]["function"] == 25
        assert parsed["density"] == 0.21
        mock_kg.get_stats.assert_called_once()
        mock_kg.close.assert_called_once()

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_stats_output_is_valid_json(self, mock_kg_class, capsys):
        """--stats output is parseable JSON."""
        mock_kg = MagicMock()
        mock_kg.get_stats.return_value = {
            "entities": 5,
            "relations": 2,
            "by_type": {"task": 5},
            "density": 0.1,
            "connected_components": 1,
        }
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        main(["--stats"])

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, dict)

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_stats_closes_kg_on_error(self, mock_kg_class):
        """KnowledgeGraph.close() is called even when get_stats raises."""
        mock_kg = MagicMock()
        mock_kg.get_stats.side_effect = RuntimeError("corrupt DB")
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        with pytest.raises(RuntimeError, match="corrupt DB"):
            main(["--stats"])

        mock_kg.close.assert_called_once()


class TestGraphCLINoArgs:
    """Test behavior when no arguments are given."""

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_no_args_prints_help(self, mock_kg_class, capsys):
        """Running with no args prints help text and still closes KG."""
        mock_kg = MagicMock()
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        main([])

        captured = capsys.readouterr()
        assert "mnemosyne-query" in captured.out or "query" in captured.out.lower()
        mock_kg.close.assert_called_once()


class TestGraphCLIQueryPrecedence:
    """Test that --stats takes precedence over --query when both given."""

    @patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph")
    def test_stats_and_query_both_given_runs_stats(self, mock_kg_class, capsys):
        """When both --stats and --query are provided, --stats takes precedence."""
        mock_kg = MagicMock()
        mock_kg.get_stats.return_value = {
            "entities": 0,
            "relations": 0,
            "by_type": {},
            "density": 0.0,
            "connected_components": 0,
        }
        mock_kg_class.return_value = mock_kg

        from mnemosyne.graph.cli import main

        main(["--stats", "--query", "entity:function[foo]"])

        mock_kg.get_stats.assert_called_once()
        mock_kg.query.assert_not_called()

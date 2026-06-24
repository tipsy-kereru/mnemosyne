"""Tests for the gh-style command-group CLI tree (ISSUE-0006 / SPEC-PACKAGE-001).

Covers:
- New command groups (ingest, graph, project, wiki, serve, mcp, config,
  retention, extension) dispatch to the correct handler.
- Legacy deprecation aliases emit exactly one ``warning:`` line to stderr
  and forward to the new handler.
- ``extension`` verbs (install/list/remove/upgrade/search/info) dispatch
  to the implemented handlers (ISSUE-0007 / SPEC-PACKAGE-001 PACKAGE-B).
- ``--help`` output contains the four gh-style sections (USAGE / OPTIONS /
  EXAMPLES / SEE ALSO).
- ``scripts/gen_manpages.py`` smoke: produces roff files with ``.TH`` /
  ``.SH`` markers for at least the three required leaf commands.
"""

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Group dispatch
# ---------------------------------------------------------------------------


class TestIngestGroupDispatch:
    def test_ingest_add_dispatches_to_run_add(self):
        from mnemosyne.cli import build_parser
        ns = build_parser().parse_args(
            ["ingest", "add", "--text", "hello", "--domain", "daily"]
        )
        assert ns.group == "ingest" and ns.verb == "add"
        assert ns.text == "hello"
        assert callable(ns.func)

    def test_ingest_update_dispatches_to_run_update(self):
        from mnemosyne.cli import build_parser
        ns = build_parser().parse_args(["ingest", "update", "--stats"])
        assert ns.group == "ingest" and ns.verb == "update"
        assert ns.stats is True

    def test_ingest_extract_dispatches_to_run_extract(self):
        from mnemosyne.cli import build_parser
        ns = build_parser().parse_args(
            ["ingest", "extract", "src/", "--domain", "coding"]
        )
        assert ns.group == "ingest" and ns.verb == "extract"
        assert ns.path == "src/"


class TestGraphGroupDispatch:
    def test_graph_query_positional(self):
        from mnemosyne.cli import build_parser
        ns = build_parser().parse_args(["graph", "query", "entity:function[foo]"])
        assert ns.group == "graph" and ns.verb == "query"
        assert ns.query == "entity:function[foo]"

    def test_graph_stats_verb(self):
        from mnemosyne.cli import build_parser
        ns = build_parser().parse_args(["graph", "stats"])
        assert ns.verb == "stats" and callable(ns.func)

    def test_graph_search_verb(self):
        from mnemosyne.cli import build_parser
        ns = build_parser().parse_args(["graph", "search", "authenticate"])
        assert ns.verb == "search" and ns.term == "authenticate"


class TestRetentionGroupDispatch:
    def test_retention_purge_verb(self):
        from mnemosyne.cli import build_parser
        ns = build_parser().parse_args(["retention", "purge", "--apply", "--days", "30"])
        assert ns.group == "retention" and ns.verb == "purge"
        assert ns.apply is True and ns.days == 30

    def test_retention_status_verb(self):
        from mnemosyne.cli import build_parser
        ns = build_parser().parse_args(["retention", "status"])
        assert ns.verb == "status"


class TestConfigGroupDispatch:
    def test_config_skill_install(self):
        from mnemosyne.cli import build_parser
        ns = build_parser().parse_args(["config", "skill", "install"])
        assert ns.config_verb == "skill"
        assert ns.skill_command == "install"

    def test_config_hook_status(self):
        from mnemosyne.cli import build_parser
        ns = build_parser().parse_args(["config", "hook", "status"])
        assert ns.config_verb == "hook"
        assert ns.hook_command == "status"


# ---------------------------------------------------------------------------
# Deprecation aliases
# ---------------------------------------------------------------------------


class TestDeprecationAliases:
    @pytest.mark.parametrize(
        "old_argv, expected_new",
        [
            (["add", "--text", "x"], "ingest add"),
            (["update", "--stats"], "ingest update"),
            (["extract", "src/"], "ingest extract"),
            (["query", "entity:function[foo]"], "graph query"),
            (["purge-retention", "--apply"], "retention purge"),
            (["skill", "install"], "config skill"),
            (["hook", "status"], "config hook"),
        ],
    )
    def test_alias_sets_deprecated_to_default(self, old_argv, expected_new):
        from mnemosyne.cli import build_parser
        ns = build_parser().parse_args(old_argv)
        assert ns._deprecated_to == expected_new

    def test_add_alias_emits_warning_and_forwards(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.cli._run_add") as mock_add:
            main(["add", "--text", "hello", "--domain", "daily"])
        mock_add.assert_called_once()
        err = capsys.readouterr().err
        assert "warning: 'mnemosyne add' is deprecated; use 'mnemosyne ingest add'" in err

    def test_query_alias_emits_warning_and_forwards(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.graph.cli.main") as mock_graph:
            main(["query", "entity:function[foo]"])
        mock_graph.assert_called_once()
        err = capsys.readouterr().err
        assert "warning: 'mnemosyne query' is deprecated; use 'mnemosyne graph query'" in err

    def test_purge_retention_alias_emits_warning(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.cli._run_purge_retention") as mock_purge:
            main(["purge-retention", "--dry-run", "--days", "90"])
        mock_purge.assert_called_once()
        err = capsys.readouterr().err
        assert "warning: 'mnemosyne purge-retention' is deprecated; use 'mnemosyne retention purge'" in err

    def test_skill_alias_emits_warning(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.cli._run_skill") as mock_skill:
            main(["skill", "install"])
        mock_skill.assert_called_once()
        err = capsys.readouterr().err
        assert "warning: 'mnemosyne skill' is deprecated; use 'mnemosyne config skill'" in err

    def test_hook_alias_emits_warning(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.cli._run_hook") as mock_hook:
            main(["hook", "status"])
        mock_hook.assert_called_once()
        err = capsys.readouterr().err
        assert "warning: 'mnemosyne hook' is deprecated; use 'mnemosyne config hook'" in err

    def test_warning_emitted_exactly_once(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.cli._run_add"):
            main(["add", "--text", "x"])
        err = capsys.readouterr().err
        warning_count = err.count("is deprecated")
        assert warning_count == 1


# ---------------------------------------------------------------------------
# Extension stub
# ---------------------------------------------------------------------------


class TestExtensionDispatch:
    """Extension verbs are implemented (ISSUE-0007) and dispatch correctly."""

    @pytest.mark.parametrize(
        "verb", ["install", "list", "remove", "upgrade", "search", "info"]
    )
    def test_extension_verb_dispatches_to_handler(self, verb):
        # Parser routes each verb to its cmd_ handler with group="extension".
        from mnemosyne.cli import build_parser

        # Each verb has a different argv signature; build a valid one.
        if verb in ("install", "remove", "info"):
            argv = ["extension", verb, "slm"]
        elif verb == "list":
            argv = ["extension", "list"]
        elif verb == "search":
            argv = ["extension", "search", "slm"]
        else:  # upgrade
            argv = ["extension", "upgrade", "--all"]
        ns = build_parser().parse_args(argv)
        assert ns.group == "extension"
        assert ns.verb == verb
        assert callable(ns.func)

    def test_extension_list_dispatches_with_no_extensions(
        self, capsys, monkeypatch, tmp_path
    ):
        # list verb prints "no extensions installed" and main returns None.
        from mnemosyne.cli import main

        monkeypatch.setenv("MNEMOSYNE_HOME", str(tmp_path))
        rc = main(["extension", "list"])
        assert rc in (0, None)
        out = capsys.readouterr().out
        assert "no extensions installed" in out

    def test_ext_alias_resolves_to_extension_group(self):
        from mnemosyne.cli import build_parser
        # argparse aliases: 'ext install slm' resolves to extension verb
        ns = build_parser().parse_args(["ext", "install", "slm"])
        assert ns.group == "extension"
        assert ns.verb == "install"

    def test_extension_no_verb_prints_usage_exit_2(self, capsys):
        from mnemosyne.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["extension"])
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# --help standardization
# ---------------------------------------------------------------------------


class TestHelpStandardization:
    def test_top_level_help_contains_usage_and_options(self, capsys):
        from mnemosyne.cli import main
        with pytest.raises(SystemExit):
            main(["--help"])
        out = capsys.readouterr().out
        assert "usage:" in out.lower()
        assert "options:" in out.lower()

    def test_ingest_help_contains_examples_and_see_also(self, capsys):
        from mnemosyne.cli import main
        with pytest.raises(SystemExit):
            main(["ingest", "--help"])
        out = capsys.readouterr().out
        assert "EXAMPLES" in out or "Examples" in out
        assert "SEE ALSO" in out

    def test_graph_help_contains_examples_and_see_also(self, capsys):
        from mnemosyne.cli import main
        with pytest.raises(SystemExit):
            main(["graph", "--help"])
        out = capsys.readouterr().out
        assert "EXAMPLES" in out or "Examples" in out
        assert "SEE ALSO" in out

    def test_retention_help_present(self, capsys):
        from mnemosyne.cli import main
        with pytest.raises(SystemExit):
            main(["retention", "--help"])
        out = capsys.readouterr().out
        assert "purge" in out and "status" in out

    def test_config_help_lists_skill_and_hook(self, capsys):
        from mnemosyne.cli import main
        with pytest.raises(SystemExit):
            main(["config", "--help"])
        out = capsys.readouterr().out
        assert "skill" in out
        assert "hook" in out

    def test_top_level_help_contains_at_least_two_examples(self, capsys):
        from mnemosyne.cli import main
        with pytest.raises(SystemExit):
            main(["--help"])
        out = capsys.readouterr().out
        assert "EXAMPLES" in out or "Examples" in out
        example_lines = [
            ln for ln in out.splitlines() if ln.strip().startswith("mnemosyne ")
        ]
        assert len(example_lines) >= 2

    def test_retention_help_contains_at_least_two_examples(self, capsys):
        from mnemosyne.cli import main
        with pytest.raises(SystemExit):
            main(["retention", "--help"])
        out = capsys.readouterr().out
        assert "EXAMPLES" in out or "Examples" in out
        example_lines = [
            ln for ln in out.splitlines() if ln.strip().startswith("mnemosyne ")
        ]
        assert len(example_lines) >= 2

    def test_config_help_contains_at_least_two_examples(self, capsys):
        from mnemosyne.cli import main
        with pytest.raises(SystemExit):
            main(["config", "--help"])
        out = capsys.readouterr().out
        assert "EXAMPLES" in out or "Examples" in out
        example_lines = [
            ln for ln in out.splitlines() if ln.strip().startswith("mnemosyne ")
        ]
        assert len(example_lines) >= 2

    def test_ingest_add_help_has_examples(self, capsys):
        from mnemosyne.cli import main
        with pytest.raises(SystemExit):
            main(["ingest", "add", "--help"])
        out = capsys.readouterr().out
        assert "EXAMPLES" in out or "Examples" in out

    def test_top_level_help_lists_new_groups(self, capsys):
        from mnemosyne.cli import main
        with pytest.raises(SystemExit):
            main(["--help"])
        out = capsys.readouterr().out
        for group in ("ingest", "graph", "retention", "config", "extension"):
            assert group in out, f"group {group} missing from top-level --help"


# ---------------------------------------------------------------------------
# Graph query normalization (positional vs --query flag)
# ---------------------------------------------------------------------------


class TestGraphQueryNormalization:
    def test_graph_query_flag_form_dispatches(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.graph.cli.main") as mock_graph:
            main(["graph", "query", "--query", "search:auth"])
        mock_graph.assert_called_once()
        argv = mock_graph.call_args.kwargs.get("argv") or mock_graph.call_args.args[0]
        assert "--query" in argv and "search:auth" in argv

    def test_legacy_query_flag_form_dispatches(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.graph.cli.main") as mock_graph:
            main(["query", "--query", "entity:function[foo]"])
        mock_graph.assert_called_once()


# ---------------------------------------------------------------------------
# Legacy global --query / --stats forwarding (REQ-PKG-006, AC-1)
# ---------------------------------------------------------------------------


class TestGlobalFlagForwarding:
    def test_global_query_flag_forwards_to_graph_query(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.graph.cli.main") as mock_graph:
            main(["--query", "entity:function[foo]"])
        mock_graph.assert_called_once()
        argv = mock_graph.call_args.kwargs.get("argv") or mock_graph.call_args.args[0]
        assert "--query" in argv and "entity:function[foo]" in argv

    def test_global_query_flag_emits_deprecation_warning(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.graph.cli.main"):
            main(["--query", "entity:function[foo]"])
        err = capsys.readouterr().err
        assert (
            "warning: 'mnemosyne --query' is deprecated; use 'mnemosyne graph query'"
            in err
        )

    def test_global_stats_flag_forwards_to_graph_stats(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.graph.cli.main") as mock_graph:
            main(["--stats"])
        mock_graph.assert_called_once()
        argv = mock_graph.call_args.kwargs.get("argv") or mock_graph.call_args.args[0]
        assert "--stats" in argv

    def test_global_stats_flag_emits_deprecation_warning(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.graph.cli.main"):
            main(["--stats"])
        err = capsys.readouterr().err
        assert (
            "warning: 'mnemosyne --stats' is deprecated; use 'mnemosyne graph stats'"
            in err
        )

    def test_subcommand_takes_precedence_over_global_flags(self):
        from mnemosyne.cli import build_parser
        # When a real subcommand is given, the global --query flag must NOT
        # override it (the group-shape path wins).
        ns = build_parser().parse_args(["graph", "query", "x"])
        assert ns.command == "graph"


# ---------------------------------------------------------------------------
# mcp REMAINDER pass-through
# ---------------------------------------------------------------------------


class TestMcpPassthrough:
    def test_mcp_install_args_forwarded(self):
        from mnemosyne.cli import main
        with patch("mnemosyne.mcp.cli.main", return_value=0) as mock_mcp:
            main(["mcp", "install", "--client", "claude-desktop"])
        mock_mcp.assert_called_once()
        forwarded = mock_mcp.call_args.args[0] if mock_mcp.call_args.args else mock_mcp.call_args.kwargs.get("argv")
        assert "install" in forwarded
        assert "--client" in forwarded

    def test_mcp_no_deprecation_warning(self, capsys):
        from mnemosyne.cli import main
        with patch("mnemosyne.mcp.cli.main", return_value=0):
            main(["mcp", "serve"])
        err = capsys.readouterr().err
        assert "deprecated" not in err


# ---------------------------------------------------------------------------
# Man-page generator smoke
# ---------------------------------------------------------------------------


class TestManpageGenerator:
    def test_generator_produces_required_pages(self, tmp_path):
        from scripts.gen_manpages import generate
        written = generate(tmp_path)
        names = {p.name for p in written}
        assert "mnemosyne-ingest-add.1" in names
        assert "mnemosyne-graph-query.1" in names
        assert "mnemosyne-retention-purge.1" in names

    def test_generated_pages_have_th_and_sh_markers(self, tmp_path):
        from scripts.gen_manpages import generate
        generate(tmp_path)
        path = tmp_path / "mnemosyne-ingest-add.1"
        text = path.read_text()
        assert text.startswith(".TH")
        assert ".SH NAME" in text
        assert ".SH OPTIONS" in text
        assert ".SH SEE ALSO" in text

    def test_generator_skips_deprecation_aliases(self, tmp_path):
        from scripts.gen_manpages import generate
        written = generate(tmp_path)
        names = {p.name for p in written}
        # Legacy alias pages must not be emitted
        assert "mnemosyne-add.1" not in names
        assert "mnemosyne-query.1" not in names
        assert "mnemosyne-purge-retention.1" not in names

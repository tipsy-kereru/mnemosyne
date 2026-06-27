"""
Mnemosyne Knowledge Graph main CLI.

Installed as ``mnemosyne`` console_scripts entry point.

Command tree (SPEC-PACKAGE-001, REQ-PKG-005):

    mnemosyne ingest <add|update|extract>
    mnemosyne graph <query|search|stats|path>
    mnemosyne project <list|show|register|unregister|migrate>
    mnemosyne wiki <status|lint|...>                 # delegates to mnemosyne.wiki.cli
    mnemosyne serve <start>
    mnemosyne mcp <serve|install>                    # REMAINDER pass-through
    mnemosyne config <get|set|list|skill|hook>
    mnemosyne retention <purge|status>
    mnemosyne extension <install|list|...>           # stub (ISSUE-0007)

Legacy top-level shapes (``add``, ``query``, ``purge-retention``, ...) are kept
as deprecation aliases for two minor releases (REQ-PKG-006). Each alias prints
exactly one ``warning:`` line to stderr before forwarding to the new handler
with identical arg semantics.
"""

import argparse
import sys

QUERY_SYNTAX = """
Query Syntax:
  search:TERM                      Fuzzy search across all entities
  entity:TYPE[NAME]                Lookup entity by type and name (supports regex)
  entity:TYPE[NAME]@session:SID    Scope query to a specific session
  entity:TYPE[NAME]@project:PID    Scope query to a specific project
  relation:TYPE                    List all relations of a given type
  path:FROM,TO                     Find shortest path between two entities

Entity types: function, class, module, api, bug, feature, test, dependency,
              task, person, place, event, habit, preference, note,
              statute, clause, case, party, obligation, deadline, contract

Examples:
  mnemosyne graph query --stats
  mnemosyne graph query "search:authenticate"
  mnemosyne graph query "entity:function[parse_config]"
  mnemosyne graph query "entity:function[.*]@session:impl-session"
  mnemosyne graph query "relation:calls"
  mnemosyne graph query "path:get_user,authenticate"

Output: JSON to stdout. Structure depends on query type.
"""

EXTRACT_EXAMPLES = """
Examples:
  mnemosyne ingest extract src/main.py
  mnemosyne ingest extract src/ --domain coding --format json
  mnemosyne ingest extract src/ --format wiki --scope-id session-1
  mnemosyne ingest extract src/ --source-channel vscode

Output:
  --format json  : Array of entity objects [{type, name, language, file_path, ...}]
  --format wiki  : Markdown with [[wiki-links]] for knowledge graph integration

Supported languages (coding domain): Python, JavaScript, TypeScript, TSX, Go, Rust
"""

ADD_EXAMPLES = """
Examples:
  mnemosyne ingest add ./notes/meeting.md
  mnemosyne ingest add https://arxiv.org/abs/2305.10601
  mnemosyne ingest add --text "John works at Google" --domain daily
  mnemosyne ingest add ./src/ --domain coding --scope-id session-1
  mnemosyne ingest add ./report.pdf --domain legal
  mnemosyne ingest add ./notes/meeting.md --wiki-root ./wiki

Output: JSON with {source, entities_added, relations_added, raw_path, wiki_paths}
  --dry-run: shows extraction preview without writing to graph
  --no-wiki: updates the knowledge graph only
"""

UPDATE_EXAMPLES = """
Examples:
  mnemosyne ingest update
  mnemosyne ingest update ~/mnemosyne/raw/coding/
  mnemosyne ingest update --stats
  mnemosyne ingest update --domain legal --prune
  mnemosyne ingest update ~/mnemosyne/raw/daily --wiki-root ~/mnemosyne/wiki

Output: JSON with {total, changed, new_files, unchanged, errors}
"""

WIKI_EXAMPLES = """
Examples:
  mnemosyne wiki status --wiki-root ~/mnemosyne/wiki
  mnemosyne wiki lint --wiki-root ~/mnemosyne/wiki --format json
  mnemosyne wiki contradictions --db-path ~/mnemosyne/graph/knowledge.db --format json
  mnemosyne wiki resolve c_abc123 --db-path ~/mnemosyne/graph/knowledge.db --resolution accepted_existing --dry-run
  mnemosyne wiki prune --db-path ~/mnemosyne/graph/knowledge.db --format json
  mnemosyne wiki semantic-contradictions --db-path ~/mnemosyne/graph/knowledge.db --write --format json
  mnemosyne wiki rebuild --wiki-root ~/mnemosyne/wiki --db-path ~/mnemosyne/graph/knowledge.db --dry-run
  mnemosyne wiki doctor --strict

Write locking:
  Wiki write commands use a .mnemosyne-wiki.lock file per wiki root.
  Use --lock-timeout on rebuild if another writer is active.

Editor workflow:
  The wiki root is editor-neutral Markdown for Joplin/Obsidian-style folders.
  Generated blocks are rebuildable; put human notes outside MNEMOSYNE markers.
  Use an explicit --wiki-root for editor vaults; no Joplin token is required.

Output: text by default; pass --format json for automation.
"""

TOP_LEVEL_EXAMPLES = """
Examples:
  mnemosyne ingest add ./notes.md --domain daily
  mnemosyne graph query "entity:function[parse_config]"
  mnemosyne retention purge --apply --days 90
  mnemosyne config skill install longdoc

Output: JSON to stdout for most verbs; --help on any group for details.

SEE ALSO:
  mnemosyne ingest, mnemosyne graph, mnemosyne retention, mnemosyne config
"""

RETENTION_EXAMPLES = """
Examples:
  mnemosyne retention purge --days 90 --dry-run
  mnemosyne retention purge --days 30 --apply
  mnemosyne retention status --days 180

Output: JSON with {purged, candidates, ...}; status is always dry-run.

SEE ALSO:
  mnemosyne config, mnemosyne graph
"""

CONFIG_EXAMPLES = """
Examples:
  mnemosyne config get extractor.model
  mnemosyne config set wiki.default_root ~/mnemosyne/wiki
  mnemosyne config list
  mnemosyne config skill install longdoc
  mnemosyne config hook install pre_ingest_validator

Output: text by default; config list prints a key=value summary.

SEE ALSO:
  mnemosyne retention, mnemosyne extension
"""

_PURGE_RETENTION_DESC = (
    "Purge chat turns older than the retention window. Tombstone-only: "
    "rows are UPDATE'd (retention_purged_at set, content overwritten "
    "with '[retention-purged]'); NO row is ever deleted (no-delete "
    "contract). Defaults to dry-run; pass --apply to write."
)

_EXTENSION_DESC = (
    "Install, list, remove, upgrade, search, or inspect mnemosyne extensions. "
    "Extensions ship heavy optional dependencies (GLiNER2/torch, pymupdf) as "
    "sidecar payloads loaded from ~/.mnemosyne/extensions/ via sys.path injection."
)
_EXTENSION_INSTALL_EXAMPLES = """\
EXAMPLES:
  # install the latest GLiNER2 + REBEL + CPU torch payload
  mnemosyne extension install slm

  # install a specific version
  mnemosyne extension install pdf --version 1.2.0

  # reinstall over an existing version
  mnemosyne extension install slm --force

  # upgrade every installed extension
  mnemosyne extension upgrade --all
"""


# ---------------------------------------------------------------------------
# gh-style help formatter (REQ-PKG-007)
# ---------------------------------------------------------------------------


class GhHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """argparse formatter that preserves the gh-style help epilog verbatim.

    Standard argparse output already emits a ``usage:`` line and an
    ``options:`` section. ``RawDescriptionHelpFormatter`` preserves the
    parser's ``description`` and ``epilog`` verbatim, so the EXAMPLES and
    SEE ALSO sections (folded into the epilog by ``_new_parser``) render
    under their own clearly-labelled banners (REQ-PKG-007).
    """


def _new_parser(
    subparsers: argparse._SubParsersAction,
    name: str,
    *,
    help: str,
    description: str,
    epilog: str | None = None,
    see_also: str | None = None,
    aliases: list[str] | None = None,
) -> argparse.ArgumentParser:
    """Create a subparser wired with GhHelpFormatter + optional SEE ALSO.

    SEE ALSO is folded into the epilog so it renders under a clearly-labelled
    section header (REQ-PKG-007). The epilog is preserved verbatim by
    GhHelpFormatter (a RawDescriptionHelpFormatter subclass).
    """
    if see_also:
        see_also_block = f"SEE ALSO:\n  {see_also}"
        epilog = f"{epilog.rstrip()}\n\n{see_also_block}" if epilog else see_also_block
    kwargs: dict = {
        "help": help,
        "description": description,
        "formatter_class": GhHelpFormatter,
    }
    if epilog:
        kwargs["epilog"] = epilog
    if aliases:
        kwargs["aliases"] = aliases
    parser = subparsers.add_parser(name, **kwargs)
    return parser


# ---------------------------------------------------------------------------
# Shared argument specs (single source for new groups + legacy aliases)
# ---------------------------------------------------------------------------


def _add_ingest_add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("target", nargs="?", help="File, directory, or URL to ingest")
    p.add_argument("--text", help="Inline text to ingest instead of a target path or URL")
    p.add_argument(
        "--domain",
        choices=["coding", "daily", "legal"],
        default="daily",
        help="Domain for ingestion (default: daily)",
    )
    p.add_argument("--scope-id", help="Attach a scope ID (e.g. session name) to ingested entities")
    p.add_argument(
        "--source-channel", default="cli", help="Tag the ingestion source channel (default: cli)"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without writing to the knowledge graph",
    )
    p.add_argument("--wiki-root", default=None, help="LLM Wiki root (default: ~/mnemosyne/wiki)")
    p.add_argument("--no-wiki", action="store_true", help="Do not update Markdown LLM Wiki pages")
    p.add_argument(
        "--wiki-excerpts", action="store_true",
        help="Opt in to bounded, redacted source excerpts in wiki source pages",
    )
    p.add_argument(
        "--examples", action="store_true", help="Show ingestion examples and output format details"
    )


def _add_ingest_update_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("path", nargs="?", help="Directory to scan (default: ~/mnemosyne/raw/)")
    p.add_argument(
        "--domain",
        choices=["coding", "daily", "legal", "auto"],
        default="auto",
        help="Domain filter (default: auto)",
    )
    p.add_argument("--scope-id", help="Attach a scope ID to updated entities")
    p.add_argument(
        "--prune", action="store_true",
        help="Remove cache entries for files that no longer exist",
    )
    p.add_argument("--stats", action="store_true", help="Show stats only, do not re-extract")
    p.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be updated without writing to the knowledge graph",
    )
    p.add_argument("--wiki-root", default=None, help="LLM Wiki root (default: ~/mnemosyne/wiki)")
    p.add_argument("--no-wiki", action="store_true", help="Do not update Markdown LLM Wiki pages")
    p.add_argument(
        "--wiki-excerpts", action="store_true",
        help="Opt in to bounded, redacted source excerpts in wiki source pages",
    )
    p.add_argument(
        "--examples", action="store_true", help="Show update examples and output format details"
    )


def _add_ingest_extract_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("path", help="File or directory to extract from")
    p.add_argument(
        "--domain",
        choices=["coding", "daily", "legal"],
        default="coding",
        help="Domain for extraction (default: coding)",
    )
    p.add_argument(
        "--format", choices=["json", "wiki"], default="json", help="Output format (default: json)"
    )
    p.add_argument(
        "--scope-id", help="Attach a scope ID (e.g. session name) to extracted entities"
    )
    p.add_argument(
        "--source-channel", default="cli", help="Tag the extraction source channel (default: cli)"
    )
    p.add_argument(
        "--examples", action="store_true", help="Show extraction examples and output format details"
    )


def _add_graph_query_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("query", nargs="?", help="Query expression (see syntax below)")
    p.add_argument("--query", dest="query_flag", help="Query expression (alias of positional)")
    p.add_argument("--stats", action="store_true", help="Show graph statistics as JSON")
    p.add_argument("--project", help="Query a specific project by name")
    p.add_argument(
        "--global",
        action="store_true",
        dest="global_scope",
        help="Search across all projects (ignore auto-scope)",
    )
    p.add_argument("--examples", action="store_true", help="Show query syntax and examples")


def _add_retention_purge_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report candidate turn count + sample IDs without writing (default)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Run the UPDATE tombstone on candidate turns (writes)",
    )
    p.add_argument(
        "--days",
        type=int,
        default=None,
        help="Retention window in days (default: MNEMOSYNE_CHAT_RETENTION_DAYS env or 90)",
    )
    p.add_argument("--db-path", default=None, help="KnowledgeGraph DB path (default: auto-resolve)")


def _add_serve_start_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=57832, help="Listen port (default: 57832)")
    p.add_argument("--db-path", default=None, help="Knowledge graph database path")


def _add_project_verbs(project_subparsers: argparse._SubParsersAction) -> None:
    _new_parser(
        project_subparsers,
        "list",
        help="List all registered projects",
        description="List all registered projects.",
    ).set_defaults(project_command="list")

    show = _new_parser(
        project_subparsers,
        "show",
        help="Show project details and entity counts",
        description="Show project details and entity counts.",
    )
    show.add_argument(
        "identifier", nargs="?", help="Project name or hash (default: current project)"
    )
    show.set_defaults(project_command="show")

    register = _new_parser(
        project_subparsers,
        "register",
        help="Manually register a project path",
        description="Manually register a project path.",
    )
    register.add_argument("path", help="Path to project root")
    register.add_argument("--name", help="Project name (default: directory basename)")
    register.set_defaults(project_command="register")

    unregister = _new_parser(
        project_subparsers,
        "unregister",
        help="Remove project registration (does not delete entities)",
        description="Remove project registration (does not delete entities).",
    )
    unregister.add_argument("identifier", help="Project name or hash")
    unregister.set_defaults(project_command="unregister")

    _new_parser(
        project_subparsers,
        "migrate",
        help="Back-fill projects table from existing scope_id values",
        description="Back-fill projects table from existing scope_id values.",
    ).set_defaults(project_command="migrate")


def _add_skill_verbs(skill_subparsers: argparse._SubParsersAction) -> None:
    skill_install = _new_parser(
        skill_subparsers,
        "install",
        help="Install mnemosyne skill to agent skills directory",
        description="Install the mnemosyne SKILL.md so that AI agents (Claude Code, etc.) can use /mnemosyne",
    )
    skill_install.add_argument(
        "--target", choices=["claude", "agents"], default="claude",
        help="Target agent framework: 'claude' for ~/.claude/skills/, 'agents' for ~/.agents/skills/ (default: claude)",
    )
    skill_install.add_argument(
        "--path",
        help="Custom absolute directory path (e.g. /home/user/.claude/skills or ./.agents/skills). Overrides --target",
    )
    skill_install.add_argument(
        "--force", action="store_true",
        help="Reinstall even if the installed SKILL.md is already identical",
    )
    skill_install.set_defaults(skill_command="install")

    skill_update = _new_parser(
        skill_subparsers,
        "update",
        help="Update installed mnemosyne skill to latest version",
        description="Update the mnemosyne SKILL.md to the latest bundled version.",
    )
    skill_update.add_argument(
        "--target", choices=["claude", "agents"], default="claude",
        help="Target agent framework (default: claude)",
    )
    skill_update.add_argument("--path", help="Custom absolute directory path. Overrides --target")
    skill_update.add_argument(
        "--force", action="store_true",
        help="Rewrite even if the installed SKILL.md is already identical",
    )
    skill_update.set_defaults(skill_command="update")


def _add_hook_verbs(hook_subparsers: argparse._SubParsersAction) -> None:
    hook_install = _new_parser(
        hook_subparsers,
        "install",
        help="Install hooks for a target platform",
        description="Install mnemosyne hooks. Without a target, installs git + claude.",
    )
    hook_install.add_argument(
        "targets", nargs="*", default=None,
        help="One or more platforms: git, claude, codex, gemini, copilot, or 'all' (default: git+claude)",
    )
    hook_install.add_argument("--force", action="store_true", help="Overwrite existing hooks")
    hook_install.set_defaults(hook_command="install")

    hook_remove = _new_parser(
        hook_subparsers, "remove", help="Remove hooks for a target platform",
        description="Remove hooks for one or more target platforms.",
    )
    hook_remove.add_argument(
        "targets", nargs="*", default=None,
        help="One or more platforms to remove hooks from (or use --all)",
    )
    hook_remove.add_argument(
        "--all", action="store_true", dest="remove_all",
        help="Remove hooks from all platforms",
    )
    hook_remove.set_defaults(hook_command="remove")

    _new_parser(
        hook_subparsers, "status", help="Show installed hook status for all platforms",
        description="Show installed hook status for all platforms.",
    ).set_defaults(hook_command="status")


def _add_extension_common(p: argparse.ArgumentParser) -> None:
    """--format json|text applies to every extension verb (REQ-PKG-007)."""
    p.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format (default: text)",
    )


def _add_extension_verbs(extension_parser: argparse.ArgumentParser) -> None:
    """Register install/list/remove/upgrade/search/info verbs (REQ-PKG-004)."""
    ext_sub = extension_parser.add_subparsers(dest="extension_command")

    install = _new_parser(
        ext_sub, "install",
        help="Install an extension payload from the registry",
        description=(
            "Download an extension payload from the registry (default: GitHub "
            "Releases of tipsy-kereru/mnemosyne-ext-<name>), verify SHA256 of "
            "every file against the signed manifest, and extract into "
            "~/.mnemosyne/extensions/<name>/<version>/."
        ),
        epilog=_EXTENSION_INSTALL_EXAMPLES,
    )
    install.add_argument("name", nargs="+", help="Extension name(s) (e.g. slm, pdf)")
    install.add_argument("--version", help="Pin a specific version (default: latest)")
    install.add_argument(
        "--force", action="store_true",
        help="Reinstall over an existing version or permit a downgrade",
    )
    _add_extension_common(install)
    install.set_defaults(func=_run_extension_install, group="extension", verb="install")

    list_p = _new_parser(
        ext_sub, "list",
        help="List installed extensions",
        description="Print installed extensions (name, version, source, path).",
    )
    _add_extension_common(list_p)
    list_p.set_defaults(func=_run_extension_list, group="extension", verb="list")

    remove = _new_parser(
        ext_sub, "remove",
        help="Remove an installed extension",
        description=(
            "Delete the extension payload directory and append a tombstone to "
            "extensions/.removed.jsonl for audit. The on-disk payload is gone; "
            "the record of its removal persists."
        ),
    )
    remove.add_argument("name", nargs="+", help="Extension name(s) to remove")
    _add_extension_common(remove)
    remove.set_defaults(func=_run_extension_remove, group="extension", verb="remove")

    upgrade = _new_parser(
        ext_sub, "upgrade",
        help="Upgrade one or all extensions to the latest release",
        description=(
            "Check the latest release tag and install if newer. Pass --all to "
            "upgrade every installed extension."
        ),
    )
    upgrade.add_argument("name", nargs="?", help="Extension to upgrade (omit with --all)")
    upgrade.add_argument(
        "--all", action="store_true", dest="upgrade_all",
        help="Upgrade every installed extension",
    )
    _add_extension_common(upgrade)
    upgrade.set_defaults(
        func=_run_extension_upgrade, group="extension", verb="upgrade", all=False
    )

    search = _new_parser(
        ext_sub, "search",
        help="Search the extension registry index",
        description="List extensions available from the registry index.",
    )
    search.add_argument("query", nargs="?", help="Optional substring filter")
    _add_extension_common(search)
    search.set_defaults(func=_run_extension_search, group="extension", verb="search")

    info = _new_parser(
        ext_sub, "info",
        help="Print metadata for an extension",
        description="Print metadata for an extension (installed or available): size, deps, what it enables.",
    )
    info.add_argument("name", help="Extension name")
    _add_extension_common(info)
    info.set_defaults(func=_run_extension_info, group="extension", verb="info")


def _add_config_verbs(
    config_subparsers: argparse._SubParsersAction,
) -> tuple[argparse.ArgumentParser, argparse.ArgumentParser, argparse.ArgumentParser]:
    """Register config verbs. Skill/hook are nested sub-subparsers."""
    get_p = _new_parser(
        config_subparsers, "get", help="Get a config value",
        description="Get a config value (stub — full impl lands in a follow-up).",
    )
    set_p = _new_parser(
        config_subparsers, "set", help="Set a config value",
        description="Set a config value (stub — full impl lands in a follow-up).",
    )
    list_p = _new_parser(
        config_subparsers, "list", help="List config values",
        description="List config values (stub — full impl lands in a follow-up).",
    )

    skill_parser = _new_parser(
        config_subparsers, "skill",
        help="Manage agent skill files",
        description="Install or manage mnemosyne agent skill files for Claude Code and other AI agents",
    )
    skill_sub = skill_parser.add_subparsers(dest="skill_command")
    _add_skill_verbs(skill_sub)
    skill_parser.set_defaults(config_verb="skill")

    hook_parser = _new_parser(
        config_subparsers, "hook",
        help="Manage mnemosyne hooks for AI agents and git",
        description="Install, remove, or check mnemosyne hooks that auto-sync the knowledge graph on file changes. Supports: git, claude, codex, gemini, copilot",
    )
    hook_sub = hook_parser.add_subparsers(dest="hook_command")
    _add_hook_verbs(hook_sub)
    hook_parser.set_defaults(config_verb="hook")

    return get_p, set_p, list_p


def _add_wiki_verbs(wiki_subparsers: argparse._SubParsersAction) -> None:
    def add_wiki_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--wiki-root", default=None, help="LLM Wiki root (default: ~/mnemosyne/wiki)")
        p.add_argument("--db-path", default=None, help="KnowledgeGraph DB path")
        p.add_argument("--format", choices=["text", "json"], default="text")
        p.add_argument(
            "--lock-timeout", type=float, default=10.0,
            help="Seconds to wait for the wiki write lock on write commands",
        )

    for name, help_text in (
        ("status", "Show read-only wiki health summary"),
        ("lint", "Lint wiki links, metadata, and graph drift"),
        ("contradictions", "List graph-backed contradiction review items"),
        ("resolve", "Update one conflict's resolution metadata without deleting evidence"),
        ("prune", "Plan stale wiki/graph reconciliation without deleting evidence"),
        ("semantic-contradictions", "Opt-in local semantic contradiction discovery"),
        ("rebuild", "Regenerate generated wiki sections from graph data"),
        ("doctor", "Run status and lint together"),
    ):
        sub = _new_parser(
            wiki_subparsers, name, help=help_text, description=help_text.rstrip(".") + "."
        )
        add_wiki_common(sub)
        if name == "contradictions":
            sub.add_argument("--all", action="store_true", help="Include resolved conflicts")
        if name == "resolve":
            sub.add_argument(
                "conflict_id",
                help="Stable conflict ID from `mnemosyne wiki contradictions`",
            )
            sub.add_argument(
                "--resolution",
                required=True,
                choices=[
                    "unresolved",
                    "accepted_existing",
                    "accepted_incoming",
                    "superseded",
                    "ambiguous",
                ],
            )
            sub.add_argument("--note", default=None, help="Optional review note")
            sub.add_argument("--reviewer", default=None, help="Optional reviewer label")
            sub.add_argument(
                "--dry-run", action="store_true",
                help="Preview the metadata update without writing",
            )
        if name == "prune":
            sub.add_argument(
                "--apply-tombstones", action="store_true",
                help="Write tombstone records without deleting pages or graph facts",
            )
        if name == "semantic-contradictions":
            sub.add_argument("--write", action="store_true", help="Persist review candidates")
            sub.add_argument(
                "--include-raw-excerpts", action="store_true",
                help="Opt in to bounded redacted raw source excerpts for local files",
            )
        if name in {"lint", "doctor"}:
            sub.add_argument("--strict", action="store_true", help="Exit nonzero on warnings too")
        if name == "rebuild":
            sub.add_argument("--dry-run", action="store_true", help="Show pages that would be written")
        sub.set_defaults(wiki_command=name)


# ---------------------------------------------------------------------------
# Top-level parser construction (group tree + legacy aliases)
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level mnemosyne argparse parser (group tree + aliases)."""
    parser = argparse.ArgumentParser(
        prog="mnemosyne",
        description="Mnemosyne Knowledge Graph - Local-first knowledge memory for AI agents",
        formatter_class=GhHelpFormatter,
        epilog=TOP_LEVEL_EXAMPLES,
    )
    parser.add_argument("--version", action="version", version="0.1.0")
    # Legacy global flags (REQ-PKG-006): --query/--stats forward to graph query /
    # graph stats with a deprecation warning. Kept for two minor releases.
    parser.add_argument(
        "--query", dest="global_query",
        help="(deprecated) alias for 'graph query'",
    )
    parser.add_argument(
        "--stats", dest="global_stats", action="store_true",
        help="(deprecated) alias for 'graph stats'",
    )

    subparsers = parser.add_subparsers(dest="command")

    # -- ingest group --
    ingest = _new_parser(
        subparsers, "ingest",
        help="Ingest sources into the knowledge graph",
        description="Ingest sources into the knowledge graph.",
        epilog=ADD_EXAMPLES,
        see_also="mnemosyne graph, mnemosyne wiki",
    )
    ingest_sub = ingest.add_subparsers(dest="ingest_command")
    ingest_add = _new_parser(
        ingest_sub, "add", help="Add a file, directory, URL, or text",
        description="Add a file, directory, URL, or text to the knowledge graph.",
        epilog=ADD_EXAMPLES,
    )
    _add_ingest_add_args(ingest_add)
    ingest_add.set_defaults(func=_run_add, group="ingest", verb="add")
    ingest_update = _new_parser(
        ingest_sub, "update", help="Incrementally update from changed files",
        description="Incrementally update the knowledge graph from changed files.",
        epilog=UPDATE_EXAMPLES,
    )
    _add_ingest_update_args(ingest_update)
    ingest_update.set_defaults(func=_run_update, group="ingest", verb="update")
    ingest_extract = _new_parser(
        ingest_sub, "extract", help="Extract entities from source files",
        description="Extract entities and relations from source files into the knowledge graph.",
        epilog=EXTRACT_EXAMPLES,
    )
    _add_ingest_extract_args(ingest_extract)
    ingest_extract.set_defaults(func=_run_extract, group="ingest", verb="extract")

    # -- graph group --
    graph = _new_parser(
        subparsers, "graph",
        help="Query the knowledge graph",
        description="Query the knowledge graph using structured expressions.",
        epilog=QUERY_SYNTAX,
        see_also="mnemosyne ingest, mnemosyne project",
    )
    graph_sub = graph.add_subparsers(dest="graph_command")
    graph_query = _new_parser(
        graph_sub, "query", help="Run a DSL query",
        description="Query the knowledge graph using structured expressions.",
        epilog=QUERY_SYNTAX,
    )
    _add_graph_query_args(graph_query)
    graph_query.set_defaults(func=_run_graph_query, group="graph", verb="query")
    graph_search = _new_parser(
        graph_sub, "search", help="Fuzzy search across all entities",
        description="Fuzzy search across all entities (search:TERM DSL shortcut).",
    )
    graph_search.add_argument("term", help="Search term")
    graph_search.set_defaults(func=_run_graph_search, group="graph", verb="search")
    graph_stats = _new_parser(
        graph_sub, "stats", help="Show graph statistics as JSON",
        description="Show graph statistics as JSON.",
    )
    graph_stats.set_defaults(func=_run_graph_stats, group="graph", verb="stats")
    graph_path = _new_parser(
        graph_sub, "path", help="Find shortest path between two entities",
        description="Find shortest path between two entities (path:FROM,TO DSL shortcut).",
    )
    graph_path.add_argument("from_entity", help="Starting entity")
    graph_path.add_argument("to_entity", help="Ending entity")
    graph_path.set_defaults(func=_run_graph_path, group="graph", verb="path")

    # -- project group (already group-shaped) --
    project = _new_parser(
        subparsers, "project",
        help="Manage project-scoped knowledge graphs",
        description="Register, list, and migrate project-scoped knowledge graphs.",
        see_also="mnemosyne graph, mnemosyne ingest",
    )
    project_sub = project.add_subparsers(dest="project_command")
    _add_project_verbs(project_sub)
    project.set_defaults(func=_run_project, group="project")

    # -- wiki group (delegates to mnemosyne.wiki.cli) --
    wiki = _new_parser(
        subparsers, "wiki",
        help="Inspect and maintain the Markdown LLM Wiki",
        description="Inspect and maintain the Markdown LLM Wiki.",
        epilog=WIKI_EXAMPLES,
        see_also="mnemosyne graph, mnemosyne ingest",
    )
    wiki_sub = wiki.add_subparsers(dest="wiki_command")
    _add_wiki_verbs(wiki_sub)
    wiki.set_defaults(func=_run_wiki, group="wiki")

    # -- serve group --
    serve = _new_parser(
        subparsers, "serve",
        help="HTTP API server commands",
        description="Start and inspect the local HTTP API server (stdlib http.server).",
    )
    serve_sub = serve.add_subparsers(dest="serve_command")
    serve_start = _new_parser(
        serve_sub, "start", help="Start HTTP API server",
        description="Start a local HTTP API server (stdlib http.server, no external dependencies).",
    )
    _add_serve_start_args(serve_start)
    serve_start.set_defaults(func=_run_serve, group="serve", verb="start")
    serve.set_defaults(func=_run_serve_group, group="serve")

    # -- mcp group (REMAINDER pass-through preserved) --
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="MCP server and install helper (SPEC-MCP-001)",
        description="Run the MCP stdio server or print an MCP client config snippet.",
    )
    # REMAINDER lets `mnemosyne mcp install --client X` pass through to the
    # mcp sub-CLI which owns its own argparse for `serve` / `install`.
    mcp_parser.add_argument("mcp_args", nargs=argparse.REMAINDER)
    mcp_parser.set_defaults(func=_run_mcp, group="mcp")

    # -- config group --
    config = _new_parser(
        subparsers, "config",
        help="Inspect and edit mnemosyne configuration",
        description="Inspect and edit mnemosyne configuration (values, skills, hooks).",
        epilog=CONFIG_EXAMPLES,
    )
    config_sub = config.add_subparsers(dest="config_command")
    get_p, set_p, list_p = _add_config_verbs(config_sub)
    get_p.set_defaults(func=_run_config_get, group="config", verb="get")
    set_p.set_defaults(func=_run_config_set, group="config", verb="set")
    list_p.set_defaults(func=_run_config_list, group="config", verb="list")
    config.set_defaults(func=_run_config_group, group="config")

    # -- retention group --
    retention = _new_parser(
        subparsers, "retention",
        help="Chat-content retention management",
        description="Purge or inspect chat-content retention (tombstone-only; no row deletion).",
        epilog=RETENTION_EXAMPLES,
    )
    retention_sub = retention.add_subparsers(dest="retention_command")
    retention_purge = _new_parser(
        retention_sub, "purge", help="Purge (tombstone) chat turns past the retention window",
        description=_PURGE_RETENTION_DESC,
    )
    _add_retention_purge_args(retention_purge)
    retention_purge.set_defaults(func=_run_purge_retention, group="retention", verb="purge")
    retention_status = _new_parser(
        retention_sub, "status", help="Report candidate turn count without writing",
        description="Report candidate turn count without writing (always dry-run).",
    )
    _add_retention_purge_args(retention_status)
    retention_status.set_defaults(func=_run_purge_retention_status, group="retention", verb="status")
    retention.set_defaults(func=_run_retention_group, group="retention")

    # -- extension group (REQ-PKG-004; ISSUE-0007 / SPEC-PACKAGE-001 PACKAGE-B) --
    extension = _new_parser(
        subparsers, "extension",
        help="Manage mnemosyne extensions",
        description=_EXTENSION_DESC,
        aliases=["ext"],
        see_also="mnemosyne config",
    )
    _add_extension_verbs(extension)
    extension.set_defaults(func=_run_extension_group, group="extension")

    # -- legacy / deprecation aliases (REQ-PKG-006) --
    _register_legacy_aliases(subparsers)

    return parser


def _register_legacy_aliases(subparsers: argparse._SubParsersAction) -> None:
    """Register legacy top-level subparsers that forward to the new groups.

    Each alias sets ``_deprecated_to`` so ``main()`` emits a single stderr
    warning before dispatching. Handler reuse avoids arg-mapping drift.
    """
    add_alias = subparsers.add_parser(
        "add",
        help="(deprecated) alias for 'ingest add'",
        description="Deprecated. Use 'mnemosyne ingest add'.",
        formatter_class=GhHelpFormatter,
    )
    _add_ingest_add_args(add_alias)
    add_alias.set_defaults(func=_run_add, _deprecated_to="ingest add")

    update_alias = subparsers.add_parser(
        "update",
        help="(deprecated) alias for 'ingest update'",
        description="Deprecated. Use 'mnemosyne ingest update'.",
        formatter_class=GhHelpFormatter,
    )
    _add_ingest_update_args(update_alias)
    update_alias.set_defaults(func=_run_update, _deprecated_to="ingest update")

    extract_alias = subparsers.add_parser(
        "extract",
        help="(deprecated) alias for 'ingest extract'",
        description="Deprecated. Use 'mnemosyne ingest extract'.",
        formatter_class=GhHelpFormatter,
        epilog=EXTRACT_EXAMPLES,
    )
    _add_ingest_extract_args(extract_alias)
    extract_alias.set_defaults(func=_run_extract, _deprecated_to="ingest extract")

    query_alias = subparsers.add_parser(
        "query",
        help="(deprecated) alias for 'graph query'",
        description="Deprecated. Use 'mnemosyne graph query'.",
        formatter_class=GhHelpFormatter,
        epilog=QUERY_SYNTAX,
    )
    _add_graph_query_args(query_alias)
    query_alias.set_defaults(func=_run_graph_query, _deprecated_to="graph query")

    purge_alias = subparsers.add_parser(
        "purge-retention",
        help="(deprecated) alias for 'retention purge'",
        description="Deprecated. Use 'mnemosyne retention purge'.",
        formatter_class=GhHelpFormatter,
    )
    _add_retention_purge_args(purge_alias)
    purge_alias.set_defaults(func=_run_purge_retention, _deprecated_to="retention purge")

    skill_alias = subparsers.add_parser(
        "skill",
        help="(deprecated) alias for 'config skill'",
        description="Deprecated. Use 'mnemosyne config skill'.",
        formatter_class=GhHelpFormatter,
    )
    skill_alias_sub = skill_alias.add_subparsers(dest="skill_command")
    _add_skill_verbs(skill_alias_sub)
    skill_alias.set_defaults(func=_run_skill, _deprecated_to="config skill")

    hook_alias = subparsers.add_parser(
        "hook",
        help="(deprecated) alias for 'config hook'",
        description="Deprecated. Use 'mnemosyne config hook'.",
        formatter_class=GhHelpFormatter,
    )
    hook_alias_sub = hook_alias.add_subparsers(dest="hook_command")
    _add_hook_verbs(hook_alias_sub)
    hook_alias.set_defaults(func=_run_hook, _deprecated_to="config hook")


def _emit_deprecation_warning(old: str, new: str) -> None:
    """Print exactly one deprecation warning line to stderr (REQ-PKG-006)."""
    print(
        f"warning: 'mnemosyne {old}' is deprecated; use 'mnemosyne {new}'",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Group help fallbacks + graph/extension/config dispatchers
# ---------------------------------------------------------------------------


def _run_serve_group(args):
    """Print serve help when ``mnemosyne serve`` is invoked with no verb."""
    print("Usage: mnemosyne serve <start> [options]", file=sys.stderr)
    sys.exit(2)


def _run_config_group(args):
    """Dispatch ``config skill`` / ``config hook`` or print help."""
    verb = getattr(args, "config_verb", None)
    if verb == "skill":
        _run_skill(args)
        return
    if verb == "hook":
        _run_hook(args)
        return
    print("Usage: mnemosyne config <get|set|list|skill|hook> [options]")


def _run_retention_group(args):
    """Print retention help when ``mnemosyne retention`` is invoked with no verb."""
    print("Usage: mnemosyne retention <purge|status> [options]", file=sys.stderr)
    sys.exit(2)


def _run_extension_group(args):
    """Print help when ``mnemosyne extension`` is invoked with no verb."""
    from mnemosyne.extensions.cli import cmd_group

    code = cmd_group(args)
    if code:
        sys.exit(code)


def _run_extension_install(args):
    from mnemosyne.extensions.cli import cmd_install

    code = cmd_install(args)
    if code:
        sys.exit(code)


def _run_extension_list(args):
    from mnemosyne.extensions.cli import cmd_list

    code = cmd_list(args)
    if code:
        sys.exit(code)


def _run_extension_remove(args):
    from mnemosyne.extensions.cli import cmd_remove

    code = cmd_remove(args)
    if code:
        sys.exit(code)


def _run_extension_upgrade(args):
    from mnemosyne.extensions.cli import cmd_upgrade

    # argparse sets `all` via the dest on set_defaults; normalize both shapes.
    if not hasattr(args, "all"):
        args.all = getattr(args, "upgrade_all", False)
    code = cmd_upgrade(args)
    if code:
        sys.exit(code)


def _run_extension_search(args):
    from mnemosyne.extensions.cli import cmd_search

    code = cmd_search(args)
    if code:
        sys.exit(code)


def _run_extension_info(args):
    from mnemosyne.extensions.cli import cmd_info

    code = cmd_info(args)
    if code:
        sys.exit(code)


def _run_config_get(args):
    """config get — stub (full impl lands in a follow-up)."""
    print("config get is not implemented yet")


def _run_config_set(args):
    """config set — stub (full impl lands in a follow-up)."""
    print("config set is not implemented yet")


def _run_config_list(args):
    """config list — stub (full impl lands in a follow-up)."""
    print("config list is not implemented yet")


def _resolve_graph_query_string(args) -> str | None:
    """Pick the query string from positional or --query flag (positional wins)."""
    positional = getattr(args, "query", None)
    flag = getattr(args, "query_flag", None)
    return positional or flag


def _run_graph_query(args):
    """Execute ``mnemosyne graph query`` (and legacy ``query`` alias)."""
    from mnemosyne.graph.cli import main as graph_main
    # Normalize: positional `query` is the source of truth; legacy --query flag
    # is mirrored into the positional slot before dispatch.
    if getattr(args, "query_flag", None) and not getattr(args, "query", None):
        args.query = args.query_flag
    _inject_project_scope(args)
    graph_main(argv=_build_query_argv(args))


def _run_graph_search(args):
    """Execute ``mnemosyne graph search`` — shortcut for ``search:TERM``."""
    from mnemosyne.graph.cli import main as graph_main
    graph_main(argv=["--query", f"search:{args.term}"])


def _run_graph_stats(args):
    """Execute ``mnemosyne graph stats``."""
    from mnemosyne.graph.cli import main as graph_main
    graph_main(argv=["--stats"])


def _run_graph_path(args):
    """Execute ``mnemosyne graph path FROM TO``."""
    from mnemosyne.graph.cli import main as graph_main
    graph_main(argv=["--query", f"path:{args.from_entity},{args.to_entity}"])


def _run_extract(args):
    """Execute ``mnemosyne ingest extract`` (and legacy ``extract`` alias)."""
    from mnemosyne.extraction.cli import main as extract_main
    extract_main(argv=_build_extract_argv(args))


def _run_mcp(args):
    """Execute the ``mnemosyne mcp`` subcommand (REMAINDER pass-through)."""
    from mnemosyne.mcp.cli import main as mcp_main
    # REMAINDER captures everything after `mcp` (incl. leading `--`).
    mcp_args = [a for a in getattr(args, "mcp_args", []) if a != "--"]
    code = mcp_main(mcp_args)
    if code:
        sys.exit(code)


def _run_purge_retention_status(args):
    """Execute ``mnemosyne retention status`` — always dry-run report."""
    import json

    from mnemosyne.query.chat_store import purge_retention

    kg = _open_kg_for_purge(args)
    try:
        result = purge_retention(kg.conn, days=args.days, apply=False)
        print(json.dumps(result, indent=2))
    finally:
        kg.close()


def main(argv=None):
    """Mnemosyne CLI entry point."""
    _load_dotenv()
    # REQ-PKG-003: inject installed extension payload dirs into sys.path
    # before CLI dispatch so optional deps (gliner/fitz/torch) resolve.
    # Best-effort: a corrupt extension must not block the CLI.
    try:
        from mnemosyne.extensions.loader import load_installed_extensions

        load_installed_extensions()
    except Exception:  # noqa: BLE001 - startup must not crash on loader errors
        pass
    parser = build_parser()
    args = parser.parse_args(argv)

    # --examples on command shapes: emit warning (if deprecated), then show epilog
    if getattr(args, "examples", False):
        command = getattr(args, "command", None)
        examples_map = {
            "query": QUERY_SYNTAX,
            "extract": EXTRACT_EXAMPLES,
            "add": ADD_EXAMPLES,
            "update": UPDATE_EXAMPLES,
            "wiki": WIKI_EXAMPLES,
        }
        if command in examples_map:
            if getattr(args, "_deprecated_to", None):
                _emit_deprecation_warning(command, args._deprecated_to)
            print(examples_map[command].strip())
            return

    # Legacy global flags (REQ-PKG-006): --query/--stats forward to graph query
    # / graph stats with a one-line deprecation warning. A subcommand, if also
    # given, takes precedence (the new group-shape path).
    if getattr(args, "command", None) is None:
        global_query = getattr(args, "global_query", None)
        global_stats = getattr(args, "global_stats", False)
        if global_query:
            _emit_deprecation_warning("--query", "graph query")
            args.query = global_query
            args.query_flag = global_query
            args.stats = bool(global_stats)
            try:
                _run_graph_query(args)
            except NotImplementedError as exc:
                parser.error(str(exc))
            return
        if global_stats:
            _emit_deprecation_warning("--stats", "graph stats")
            try:
                _run_graph_stats(args)
            except NotImplementedError as exc:
                parser.error(str(exc))
            return

    func = getattr(args, "func", None)
    if func is None:
        # No subcommand (or group with no verb). Render help.
        parser.print_help()
        return

    # Deprecation warning fires exactly once, right before dispatch.
    deprecated_to = getattr(args, "_deprecated_to", None)
    if deprecated_to:
        command = getattr(args, "command", "")
        _emit_deprecation_warning(command, deprecated_to)

    try:
        func(args)
    except NotImplementedError as exc:
        # Extension stubs: argparse-style exit code 2 with a clear message.
        parser.error(str(exc))


def _load_dotenv() -> None:
    """Best-effort .env discovery (mirrors prior behaviour)."""
    try:
        from pathlib import Path
        from dotenv import load_dotenv  # type: ignore[import-not-found]
        # Frozen-import compatibility (PyOxidizer / ISSUE-0008 PACKAGE-C):
        # Read `__file__` via sys.modules so it resolves to this module's
        # frozen-import path (or None when unavailable), independent of the
        # caller's exec scope. PyOxidizer's frozen importer leaves `__file__`
        # as None for frozen modules; the legacy bare `__file__` reference
        # crashed the binary on startup in that case.
        import sys as _sys
        _this_module = _sys.modules.get(__name__)
        module_file = getattr(_this_module, "__file__", None) if _this_module else None
        if not module_file:
            load_dotenv()
            return
        current = Path(module_file).resolve().parent
        for _ in range(4):
            env_path = current / ".env"
            if env_path.exists():
                load_dotenv(dotenv_path=env_path)
                return
            current = current.parent
        load_dotenv()
    except ImportError:
        pass


def _build_query_argv(args):
    """Build argv list for graph CLI from parsed args."""
    argv: list[str] = []
    if getattr(args, "stats", False):
        argv.append("--stats")
    query = _resolve_graph_query_string(args)
    if query:
        argv.extend(["--query", query])
    return argv


def _build_extract_argv(args):
    """Build argv list for extraction CLI from parsed args."""
    argv = [args.path, "--domain", args.domain, "--format", args.format]
    if args.scope_id:
        argv.extend(["--scope-id", args.scope_id])
    if args.source_channel != "cli":
        argv.extend(["--source-channel", args.source_channel])
    return argv


def _run_add(args):
    """Execute the ``mnemosyne ingest add`` subcommand."""
    import json
    import sys
    from pathlib import Path

    from mnemosyne.ingest.ingester import Ingester

    default_wiki = Path.home() / "mnemosyne" / "wiki"
    wiki_root = None if getattr(args, "no_wiki", False) else Path(
        getattr(args, "wiki_root", None) or default_wiki
    )
    ingester = Ingester(
        wiki_root=wiki_root,
        include_wiki_excerpts=getattr(args, "wiki_excerpts", False),
        dry_run=getattr(args, "dry_run", False),
    )
    target = getattr(args, "target", None)
    text = getattr(args, "text", None)

    if not target and not text:
        print("Error: provide a target (file/URL) or --text", file=sys.stderr)
        sys.exit(1)

    result = ingester.add(
        target=target or "",
        domain=args.domain,
        scope_id=getattr(args, "scope_id", None),
        source_channel=getattr(args, "source_channel", "cli"),
        text=text,
        auto_scope=True,
    )

    # Directory ingestion returns a list of results — summarize them.
    if isinstance(result, list):
        total_e = sum(r.entities_added for r in result)
        total_r = sum(r.relations_added for r in result)
        print(json.dumps({
            "sources": len(result),
            "entities_added": total_e,
            "relations_added": total_r,
        }))
    else:
        out = {
            "source": result.source,
            "entities_added": result.entities_added,
            "relations_added": result.relations_added,
            "raw_path": str(result.raw_path) if result.raw_path else None,
            "wiki_paths": [str(path) for path in getattr(result, "wiki_paths", [])],
        }
        if getattr(result, "skipped", False):
            out["skipped"] = True
            out["skip_reason"] = getattr(result, "skip_reason", None)
        print(json.dumps(out))


def _run_update(args):
    """Execute the ``mnemosyne update`` subcommand."""
    import json
    from pathlib import Path

    from mnemosyne.ingest.update import Updater

    path = Path(args.path) if getattr(args, "path", None) else None
    domain = getattr(args, "domain", "auto")
    domain_filter = None if domain == "auto" else domain

    default_wiki = Path.home() / "mnemosyne" / "wiki"
    wiki_root = None if getattr(args, "no_wiki", False) else Path(
        getattr(args, "wiki_root", None) or default_wiki
    )
    updater = Updater(
        wiki_root=wiki_root,
        include_wiki_excerpts=getattr(args, "wiki_excerpts", False),
        dry_run=getattr(args, "dry_run", False),
    )
    stats = updater.update(
        path=path,
        domain=domain_filter,
        scope_id=getattr(args, "scope_id", None),
        prune=getattr(args, "prune", False),
    )
    print(json.dumps({
        "total": stats.total,
        "changed": stats.changed,
        "new_files": stats.new_files,
        "unchanged": stats.unchanged,
        "errors": stats.errors,
    }))


def _run_skill(args):
    """Execute the ``mnemosyne skill`` subcommands."""
    import importlib.resources
    from pathlib import Path

    if args.skill_command is None:
        print("Usage: mnemosyne skill {install|update} [--target claude|agents] [--path DIR] [--force]")
        return

    if args.skill_command in ("install", "update"):
        # Read the bundled SKILL.md. In pip installs importlib.resources works,
        # but in the PyOxidizer frozen binary the non-Python data file is not
        # readable that way (ValueError), so prefer the build-baked constant.
        content: str | None = None
        try:
            from mnemosyne._skill_bundled import SKILL_MD as _baked

            content = _baked
        except ImportError:
            try:
                skill_module = importlib.resources.files("mnemosyne.skills")
                source = skill_module / "SKILL.md"
                content = source.read_text(encoding="utf-8")
            except (FileNotFoundError, AttributeError, ValueError) as exc:
                print(f"Error: Could not read bundled skill file: {exc}")
                return
        if content is None:
            print("Error: Could not read bundled skill file")
            return

        # Resolve target directory
        if getattr(args, "path", None):
            skills_dir = Path(args.path)
        elif getattr(args, "target", "claude") == "agents":
            skills_dir = Path.home() / ".agents" / "skills"
        else:
            skills_dir = Path.home() / ".claude" / "skills"

        target_file = skills_dir / "mnemosyne" / "SKILL.md"

        # Skip if already installed with identical content, unless --force reinstalls
        force = bool(getattr(args, "force", False))
        if not force and target_file.exists() and target_file.read_text(encoding="utf-8") == content:
            print(f"Already up to date: {target_file}")
            return

        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(content, encoding="utf-8")

        verb = "Updated" if args.skill_command == "update" else "Installed"
        print(f"{verb} mnemosyne skill to: {target_file}")
        print("  Trigger: /mnemosyne")
        print("  Agent:   Claude Code (or any skill-compatible AI agent)")


def _run_wiki(args):
    """Execute the ``mnemosyne wiki`` subcommands."""
    import sys
    from pathlib import Path

    from mnemosyne.wiki.cli import main as wiki_main

    argv = []
    if getattr(args, "wiki_command", None):
        argv.append(args.wiki_command)
    if getattr(args, "wiki_root", None):
        argv.extend(["--wiki-root", args.wiki_root])
    if getattr(args, "db_path", None):
        argv.extend(["--db-path", args.db_path])
    if getattr(args, "format", "text") != "text":
        argv.extend(["--format", args.format])
    if getattr(args, "lock_timeout", 10.0) != 10.0:
        argv.extend(["--lock-timeout", str(args.lock_timeout)])
    if getattr(args, "all", False):
        argv.append("--all")
    if getattr(args, "conflict_id", None):
        argv.append(args.conflict_id)
    if getattr(args, "resolution", None):
        argv.extend(["--resolution", args.resolution])
    if getattr(args, "note", None):
        argv.extend(["--note", args.note])
    if getattr(args, "reviewer", None):
        argv.extend(["--reviewer", args.reviewer])
    if getattr(args, "apply_tombstones", False):
        argv.append("--apply-tombstones")
    if getattr(args, "write", False):
        argv.append("--write")
    if getattr(args, "include_raw_excerpts", False):
        argv.append("--include-raw-excerpts")
    if getattr(args, "strict", False):
        argv.append("--strict")
    if getattr(args, "dry_run", False):
        argv.append("--dry-run")
    if not getattr(args, "wiki_root", None):
        # Keep the default visible to the delegated CLI while allowing direct tests
        # to assert against the same default path.
        argv.extend(["--wiki-root", str(Path.home() / "mnemosyne" / "wiki")])
    code = wiki_main(argv)
    if code:
        sys.exit(code)


def _run_hook(args):
    """Execute the ``mnemosyne hook`` subcommands."""
    from mnemosyne.hooks.cli import install, remove, status

    cmd = getattr(args, "hook_command", None)
    if cmd is None:
        print("Usage: mnemosyne hook {install|remove|status} [target]")
        return

    if cmd == "install":
        install(getattr(args, "targets", None), force=getattr(args, "force", False))
    elif cmd == "remove":
        remove(getattr(args, "targets", None), remove_all=getattr(args, "remove_all", False))
    elif cmd == "status":
        status()


def _inject_project_scope(args):
    """Inject @project: modifier into the query string based on --project or auto-detection."""
    if getattr(args, "global_scope", False):
        return
    if not hasattr(args, "query") or not args.query:
        return

    project_name = getattr(args, "project", None)
    if project_name:
        if "@project:" not in args.query:
            args.query = f"{args.query}@project:{project_name}"
        return

    # Auto-detect current project
    from mnemosyne.graph.project import detect_project
    from mnemosyne.graph.knowledge_graph import KnowledgeGraph

    result = detect_project()
    if result is None:
        return

    _, project_hash = result
    kg = KnowledgeGraph()
    try:
        project = kg.get_project_by_hash(project_hash)
        if project and "@project:" not in args.query:
            args.query = f"{args.query}@project:{project['project_name']}"
    finally:
        kg.close()


def _run_project(args):
    """Execute the ``mnemosyne project`` subcommands."""
    import json
    from pathlib import Path

    from mnemosyne.graph.knowledge_graph import KnowledgeGraph
    from mnemosyne.graph.project import detect_project

    cmd = getattr(args, "project_command", None)
    if cmd is None:
        print("Usage: mnemosyne project {list|show|register|unregister|migrate}")
        return

    kg = KnowledgeGraph()

    try:
        if cmd == "list":
            projects = kg.list_projects()
            if not projects:
                print("No projects registered.")
                return
            for p in projects:
                print(f"  {p['project_name']:20s} {p['entity_count']:>4d} entities  {p['project_path']}")

        elif cmd == "show":
            identifier = getattr(args, "identifier", None)
            project = None
            if identifier:
                project = kg.get_project_by_name(identifier) or kg.get_project_by_hash(identifier)
            else:
                result = detect_project()
                if result:
                    _, phash = result
                    project = kg.get_project_by_hash(phash)

            if not project:
                print("Project not found." if identifier else "No project detected in current directory.")
                return

            scope_id = project.get("scope_id")
            entity_count = 0
            if scope_id:
                row = kg.conn.execute(
                    "SELECT COUNT(*) FROM entities WHERE scope_id = ?", (scope_id,)
                ).fetchone()
                entity_count = row[0]

            print(json.dumps({
                "name": project["project_name"],
                "hash": project["project_hash"],
                "path": project["project_path"],
                "scope_id": scope_id,
                "domain": project.get("domain", "coding"),
                "entity_count": entity_count,
                "created_at": project.get("created_at"),
            }, indent=2))

        elif cmd == "register":
            path = Path(args.path).resolve()
            if not path.is_dir():
                print(f"Error: {args.path} is not a directory")
                return
            import hashlib
            phash = hashlib.sha256(str(path).encode()).hexdigest()
            name = args.name or path.name
            scope_id = kg.register_project(
                project_hash=phash,
                project_name=name,
                project_path=str(path),
            )
            print(f"Registered project '{name}' with scope_id={scope_id}")

        elif cmd == "unregister":
            identifier = args.identifier
            project = kg.get_project_by_name(identifier) or kg.get_project_by_hash(identifier)
            if not project:
                print(f"Project '{identifier}' not found.")
                return
            if kg.unregister_project(project["project_hash"]):
                print(f"Unregistered project '{project['project_name']}' (entities preserved)")

        elif cmd == "migrate":
            _run_project_migrate(kg)

    finally:
        kg.close()


def _run_project_migrate(kg):
    """Back-fill projects table from existing scope_id values."""
    import json
    from mnemosyne.timestamps import utc_now_iso

    cursor = kg.conn.cursor()
    scope_ids = cursor.execute(
        "SELECT DISTINCT scope_id FROM entities WHERE scope_id IS NOT NULL"
    ).fetchall()

    migrated = 0
    for row in scope_ids:
        sid = row["scope_id"]

        existing = cursor.execute(
            "SELECT 1 FROM projects WHERE scope_id = ?", (sid,)
        ).fetchone()
        if existing:
            continue

        scope = kg.get_scope(sid)
        if scope is None:
            continue

        now = utc_now_iso()
        project_name = scope.name
        project_hash = f"migrated-{sid[:16]}"

        cursor.execute(
            """INSERT INTO projects
               (project_hash, project_name, project_path, scope_id, domain, created_at, updated_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_hash, project_name, None, sid, "coding", now, now, json.dumps({"migrated": True})),
        )
        migrated += 1

    kg.conn.commit()
    print(f"Migrated {migrated} orphan scope(s) into projects table.")


def _run_purge_retention(args):
    """Execute the ``mnemosyne purge-retention`` subcommand (ISSUE-0004).

    Tombstone-only chat-content purge. Defaults to dry-run (zero writes).
    ``--apply`` runs the UPDATE (sets ``retention_purged_at`` + overwrites
    ``content`` with ``[retention-purged]``). NEVER issues a DELETE — the
    no-delete contract is load-bearing (security-phase grep target).
    """
    import json

    from mnemosyne.query.chat_store import purge_retention

    kg = _open_kg_for_purge(args)
    try:
        result = purge_retention(
            kg.conn, days=args.days, apply=bool(args.apply)
        )
        print(json.dumps(result, indent=2))
    finally:
        kg.close()


def _open_kg_for_purge(args):
    """Open a KnowledgeGraph for the purge job, honouring --db-path."""
    from mnemosyne.graph.knowledge_graph import KnowledgeGraph

    db_path = getattr(args, "db_path", None)
    if db_path:
        return KnowledgeGraph(db_path=db_path)
    return KnowledgeGraph()


def _run_serve(args):
    """Execute the ``mnemosyne serve`` subcommand."""
    from mnemosyne.serve.app import serve

    serve(
        host=args.host,
        port=args.port,
        db_path=args.db_path,
    )


if __name__ == "__main__":
    main()

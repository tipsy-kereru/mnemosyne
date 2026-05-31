"""
Mnemosyne Knowledge Graph main CLI.

Installed as ``mnemosyne`` console_scripts entry point.
"""

import argparse

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
  mnemosyne query --stats
  mnemosyne query --query "search:authenticate"
  mnemosyne query --query "entity:function[parse_config]"
  mnemosyne query --query "entity:function[.*]@session:impl-session"
  mnemosyne query --query "relation:calls"
  mnemosyne query --query "path:get_user,authenticate"

Output: JSON to stdout. Structure depends on query type.
"""

EXTRACT_EXAMPLES = """
Examples:
  mnemosyne extract src/main.py
  mnemosyne extract src/ --domain coding --format json
  mnemosyne extract src/ --format wiki --scope-id session-1
  mnemosyne extract src/ --source-channel vscode

Output:
  --format json  : Array of entity objects [{type, name, language, file_path, ...}]
  --format wiki  : Markdown with [[wiki-links]] for knowledge graph integration

Supported languages (coding domain): Python, JavaScript, TypeScript, TSX, Go, Rust
"""

ADD_EXAMPLES = """
Examples:
  mnemosyne add ./notes/meeting.md
  mnemosyne add https://arxiv.org/abs/2305.10601
  mnemosyne add --text "John works at Google" --domain daily
  mnemosyne add ./src/ --domain coding --scope-id session-1
  mnemosyne add ./report.pdf --domain legal
  mnemosyne add ./notes/meeting.md --wiki-root ./wiki

Output: JSON with {source, entities_added, relations_added, raw_path, wiki_paths}
  --dry-run: shows extraction preview without writing to graph
  --no-wiki: updates the knowledge graph only
"""

UPDATE_EXAMPLES = """
Examples:
  mnemosyne update
  mnemosyne update ~/mnemosyne/raw/coding/
  mnemosyne update --stats
  mnemosyne update --domain legal --prune
  mnemosyne update ~/mnemosyne/raw/daily --wiki-root ~/mnemosyne/wiki

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


def main(argv=None):
    """Mnemosyne CLI entry point."""
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
        load_dotenv()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(
        prog="mnemosyne",
        description="Mnemosyne Knowledge Graph - Local-first knowledge memory for AI agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version="0.1.0",
    )

    subparsers = parser.add_subparsers(dest="command")

    # query subcommand
    query_parser = subparsers.add_parser(
        "query",
        help="Query the knowledge graph",
        description="Query the knowledge graph using structured expressions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=QUERY_SYNTAX,
    )
    query_parser.add_argument("--query", help="Query expression (see syntax below)")
    query_parser.add_argument("--stats", action="store_true", help="Show graph statistics as JSON")
    query_parser.add_argument("--project", help="Query a specific project by name")
    query_parser.add_argument("--global", action="store_true", dest="global_scope", help="Search across all projects (ignore auto-scope)")
    query_parser.add_argument(
        "--examples", action="store_true",
        help="Show query syntax and examples",
    )

    # extract subcommand
    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract entities from source files",
        description="Extract entities and relations from source files into the knowledge graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXTRACT_EXAMPLES,
    )
    extract_parser.add_argument("path", help="File or directory to extract from")
    extract_parser.add_argument(
        "--domain",
        choices=["coding", "daily", "legal"],
        default="coding",
        help="Domain for extraction (default: coding)",
    )
    extract_parser.add_argument(
        "--format",
        choices=["json", "wiki"],
        default="json",
        help="Output format (default: json)",
    )
    extract_parser.add_argument(
        "--scope-id",
        help="Attach a scope ID (e.g. session name) to extracted entities",
    )
    extract_parser.add_argument(
        "--source-channel", default="cli",
        help="Tag the extraction source channel (default: cli)",
    )
    extract_parser.add_argument(
        "--examples", action="store_true",
        help="Show extraction examples and output format details",
    )

    # add subcommand
    add_parser = subparsers.add_parser(
        "add",
        help="Add a file, directory, URL, or text to the knowledge graph",
        description="Add a file, directory, URL, or text to the knowledge graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=ADD_EXAMPLES,
    )
    add_parser.add_argument(
        "target", nargs="?",
        help="File, directory, or URL to ingest",
    )
    add_parser.add_argument(
        "--text",
        help="Inline text to ingest instead of a target path or URL",
    )
    add_parser.add_argument(
        "--domain",
        choices=["coding", "daily", "legal"],
        default="daily",
        help="Domain for ingestion (default: daily)",
    )
    add_parser.add_argument(
        "--scope-id",
        help="Attach a scope ID (e.g. session name) to ingested entities",
    )
    add_parser.add_argument(
        "--source-channel", default="cli",
        help="Tag the ingestion source channel (default: cli)",
    )
    add_parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without writing to the knowledge graph",
    )
    add_parser.add_argument(
        "--wiki-root",
        default=None,
        help="LLM Wiki root (default: ~/mnemosyne/wiki)",
    )
    add_parser.add_argument(
        "--no-wiki", action="store_true",
        help="Do not update Markdown LLM Wiki pages",
    )
    add_parser.add_argument(
        "--wiki-excerpts", action="store_true",
        help="Opt in to bounded, redacted source excerpts in wiki source pages",
    )
    add_parser.add_argument(
        "--examples", action="store_true",
        help="Show ingestion examples and output format details",
    )

    # update subcommand
    update_parser = subparsers.add_parser(
        "update",
        help="Incrementally update the knowledge graph from changed files",
        description="Incrementally update the knowledge graph from changed files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=UPDATE_EXAMPLES,
    )
    update_parser.add_argument(
        "path", nargs="?",
        help="Directory to scan (default: ~/mnemosyne/raw/)",
    )
    update_parser.add_argument(
        "--domain",
        choices=["coding", "daily", "legal", "auto"],
        default="auto",
        help="Domain filter (default: auto)",
    )
    update_parser.add_argument(
        "--scope-id",
        help="Attach a scope ID to updated entities",
    )
    update_parser.add_argument(
        "--prune", action="store_true",
        help="Remove cache entries for files that no longer exist",
    )
    update_parser.add_argument(
        "--stats", action="store_true",
        help="Show stats only, do not re-extract",
    )
    update_parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be updated without writing to the knowledge graph",
    )
    update_parser.add_argument(
        "--wiki-root",
        default=None,
        help="LLM Wiki root (default: ~/mnemosyne/wiki)",
    )
    update_parser.add_argument(
        "--no-wiki", action="store_true",
        help="Do not update Markdown LLM Wiki pages",
    )
    update_parser.add_argument(
        "--wiki-excerpts", action="store_true",
        help="Opt in to bounded, redacted source excerpts in wiki source pages",
    )
    update_parser.add_argument(
        "--examples", action="store_true",
        help="Show update examples and output format details",
    )

    # -- skill subcommand --
    skill_parser = subparsers.add_parser(
        "skill",
        help="Manage agent skill files",
        description="Install or manage mnemosyne agent skill files for Claude Code and other AI agents",
    )
    skill_subparsers = skill_parser.add_subparsers(dest="skill_command")

    skill_install = skill_subparsers.add_parser(
        "install",
        help="Install mnemosyne skill to agent skills directory",
        description="Install the mnemosyne SKILL.md so that AI agents (Claude Code, etc.) can use /mnemosyne",
    )
    skill_install.add_argument(
        "--target", choices=["claude", "agents"], default="claude",
        help="Target agent framework: 'claude' for ~/.claude/skills/, 'agents' for ./.agents/skills/ (default: claude)",
    )
    skill_install.add_argument(
        "--path",
        help="Custom absolute directory path (e.g. /home/user/.claude/skills). Overrides --target",
    )

    skill_update = skill_subparsers.add_parser(
        "update",
        help="Update installed mnemosyne skill to latest version",
        description="Update the mnemosyne SKILL.md to the latest bundled version",
    )
    skill_update.add_argument(
        "--target", choices=["claude", "agents"], default="claude",
        help="Target agent framework (default: claude)",
    )
    skill_update.add_argument(
        "--path",
        help="Custom absolute directory path. Overrides --target",
    )

    # -- hook subcommand --
    hook_parser = subparsers.add_parser(
        "hook",
        help="Manage mnemosyne hooks for AI agents and git",
        description="Install, remove, or check mnemosyne hooks that auto-sync the "
        "knowledge graph on file changes. Supports: git, claude, codex, gemini, copilot",
    )
    hook_subparsers = hook_parser.add_subparsers(dest="hook_command")

    hook_install = hook_subparsers.add_parser(
        "install",
        help="Install hooks for a target platform",
        description="Install mnemosyne hooks. Without a target, installs git + claude.",
    )
    hook_install.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Platform: git, claude, codex, gemini, copilot, or 'all' (default: git+claude)",
    )
    hook_install.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing hooks",
    )

    hook_remove = hook_subparsers.add_parser(
        "remove",
        help="Remove hooks for a target platform",
    )
    hook_remove.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Platform to remove hooks from",
    )
    hook_remove.add_argument(
        "--all",
        action="store_true",
        dest="remove_all",
        help="Remove hooks from all platforms",
    )

    hook_subparsers.add_parser(
        "status",
        help="Show installed hook status for all platforms",
    )

    # -- serve subcommand --
    serve_parser = subparsers.add_parser(
        "serve",
        help="Start HTTP API server for external tool integration",
        description="Start a local HTTP API server (stdlib http.server, no external dependencies)",
    )
    serve_parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port", type=int, default=57832,
        help="Listen port (default: 57832)",
    )
    serve_parser.add_argument(
        "--db-path", default=None,
        help="Knowledge graph database path",
    )

    wiki_parser = subparsers.add_parser(
        "wiki",
        help="Inspect and maintain the Markdown LLM Wiki",
        description="Inspect and maintain the Markdown LLM Wiki",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=WIKI_EXAMPLES,
    )

    # -- project subcommand --
    project_parser = subparsers.add_parser(
        "project",
        help="Manage project-scoped knowledge graphs",
        description="Register, list, and migrate project-scoped knowledge graphs",
    )
    project_subparsers = project_parser.add_subparsers(dest="project_command")

    project_subparsers.add_parser(
        "list",
        help="List all registered projects",
    )

    project_show = project_subparsers.add_parser(
        "show",
        help="Show project details and entity counts",
    )
    project_show.add_argument(
        "identifier",
        nargs="?",
        help="Project name or hash (default: current project)",
    )

    project_register = project_subparsers.add_parser(
        "register",
        help="Manually register a project path",
    )
    project_register.add_argument("path", help="Path to project root")
    project_register.add_argument("--name", help="Project name (default: directory basename)")

    project_unregister = project_subparsers.add_parser(
        "unregister",
        help="Remove project registration (does not delete entities)",
    )
    project_unregister.add_argument("identifier", help="Project name or hash")

    project_subparsers.add_parser(
        "migrate",
        help="Back-fill projects table from existing scope_id values",
    )
    wiki_subparsers = wiki_parser.add_subparsers(dest="wiki_command")

    def add_wiki_common(p):
        p.add_argument("--wiki-root", default=None, help="LLM Wiki root (default: ~/mnemosyne/wiki)")
        p.add_argument("--db-path", default=None, help="KnowledgeGraph DB path")
        p.add_argument("--format", choices=["text", "json"], default="text")
        p.add_argument("--lock-timeout", type=float, default=10.0, help="Seconds to wait for the wiki write lock on write commands")

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
        sub = wiki_subparsers.add_parser(name, help=help_text)
        add_wiki_common(sub)
        if name == "contradictions":
            sub.add_argument("--all", action="store_true", help="Include resolved conflicts")
        if name == "resolve":
            sub.add_argument("conflict_id", help="Stable conflict ID from `mnemosyne wiki contradictions`")
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
            sub.add_argument("--dry-run", action="store_true", help="Preview the metadata update without writing")
        if name == "prune":
            sub.add_argument(
                "--apply-tombstones",
                action="store_true",
                help="Write tombstone records without deleting pages or graph facts",
            )
        if name == "semantic-contradictions":
            sub.add_argument("--write", action="store_true", help="Persist review candidates")
            sub.add_argument(
                "--include-raw-excerpts",
                action="store_true",
                help="Opt in to bounded redacted raw source excerpts for local files",
            )
        if name in {"lint", "doctor"}:
            sub.add_argument("--strict", action="store_true", help="Exit nonzero on warnings too")
        if name == "rebuild":
            sub.add_argument("--dry-run", action="store_true", help="Show pages that would be written")

    args = parser.parse_args(argv)

    if getattr(args, "examples", False):
        if args.command == "query":
            print(QUERY_SYNTAX.strip())
        elif args.command == "extract":
            print(EXTRACT_EXAMPLES.strip())
        elif args.command == "add":
            print(ADD_EXAMPLES.strip())
        elif args.command == "update":
            print(UPDATE_EXAMPLES.strip())
        elif args.command == "wiki":
            print(WIKI_EXAMPLES.strip())
        return

    if args.command is None:
        parser.print_help()
    elif args.command == "query":
        from mnemosyne.graph.cli import main as graph_main
        _inject_project_scope(args)
        graph_main(argv=_build_query_argv(args))
    elif args.command == "extract":
        from mnemosyne.extraction.cli import main as extract_main
        extract_main(argv=_build_extract_argv(args))
    elif args.command == "add":
        _run_add(args)
    elif args.command == "update":
        _run_update(args)
    elif args.command == "wiki":
        _run_wiki(args)
    elif args.command == "skill":
        _run_skill(args)
    elif args.command == "hook":
        _run_hook(args)
    elif args.command == "project":
        _run_project(args)
    elif args.command == "serve":
        _run_serve(args)
    else:
        parser.print_help()


def _build_query_argv(args):
    """Build argv list for graph CLI from parsed args."""
    argv = []
    if args.stats:
        argv.append("--stats")
    if args.query:
        argv.extend(["--query", args.query])
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
    """Execute the ``mnemosyne add`` subcommand."""
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
        print("Usage: mnemosyne skill {install|update} [--target claude|agents] [--path DIR]")
        return

    if args.skill_command in ("install", "update"):
        # Read the bundled SKILL.md from package data
        try:
            skill_module = importlib.resources.files("mnemosyne.skills")
            source = skill_module / "SKILL.md"
            content = source.read_text(encoding="utf-8")
        except (FileNotFoundError, AttributeError) as exc:
            print(f"Error: Could not read bundled skill file: {exc}")
            return

        # Resolve target directory
        if getattr(args, "path", None):
            skills_dir = Path(args.path)
        elif getattr(args, "target", "claude") == "agents":
            skills_dir = Path.cwd() / ".agents" / "skills"
        else:
            skills_dir = Path.home() / ".claude" / "skills"

        target_file = skills_dir / "mnemosyne" / "SKILL.md"

        # Check if already installed with identical content
        if target_file.exists() and target_file.read_text(encoding="utf-8") == content:
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
        install(getattr(args, "target", None), force=getattr(args, "force", False))
    elif cmd == "remove":
        remove(getattr(args, "target", None), remove_all=getattr(args, "remove_all", False))
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

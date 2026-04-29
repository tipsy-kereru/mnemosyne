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

Output: JSON with {source, entities_added, relations_added, raw_path}
  --dry-run: shows extraction preview without writing to graph
"""

UPDATE_EXAMPLES = """
Examples:
  mnemosyne update
  mnemosyne update ~/mnemosyne/raw/coding/
  mnemosyne update --stats
  mnemosyne update --domain legal --prune

Output: JSON with {total, changed, new_files, unchanged, errors}
"""


def main(argv=None):
    """Mnemosyne CLI entry point."""
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
        "--examples", action="store_true",
        help="Show update examples and output format details",
    )

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
        return

    if args.command is None:
        parser.print_help()
    elif args.command == "query":
        from mnemosyne.graph.cli import main as graph_main
        graph_main(argv=_build_query_argv(args))
    elif args.command == "extract":
        from mnemosyne.extraction.cli import main as extract_main
        extract_main(argv=_build_extract_argv(args))
    elif args.command == "add":
        _run_add(args)
    elif args.command == "update":
        _run_update(args)
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

    from mnemosyne.ingest.ingester import Ingester

    ingester = Ingester(dry_run=getattr(args, "dry_run", False))
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

    updater = Updater(dry_run=getattr(args, "dry_run", False))
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


if __name__ == "__main__":
    main()

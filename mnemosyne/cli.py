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

    args = parser.parse_args(argv)

    if getattr(args, "examples", False):
        if args.command == "query":
            print(QUERY_SYNTAX.strip())
        elif args.command == "extract":
            print(EXTRACT_EXAMPLES.strip())
        return

    if args.command is None:
        parser.print_help()
    elif args.command == "query":
        from mnemosyne.graph.cli import main as graph_main
        graph_main(argv=_build_query_argv(args))
    elif args.command == "extract":
        from mnemosyne.extraction.cli import main as extract_main
        extract_main(argv=_build_extract_argv(args))
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


if __name__ == "__main__":
    main()

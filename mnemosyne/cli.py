"""
Mnemosyne Knowledge Graph main CLI.

Installed as ``mnemosyne`` console_scripts entry point.
"""

import argparse
import sys


def main(argv=None):
    """Mnemosyne CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mnemosyne",
        description="Mnemosyne Knowledge Graph - Local-first knowledge memory for AI agents",
    )
    parser.add_argument(
        "--version", action="version", version="0.1.0",
    )

    subparsers = parser.add_subparsers(dest="command")

    # query subcommand
    query_parser = subparsers.add_parser("query", help="Query the knowledge graph")
    query_parser.add_argument("--query", help="Query expression")
    query_parser.add_argument("--stats", action="store_true", help="Show graph statistics")

    # extract subcommand
    extract_parser = subparsers.add_parser("extract", help="Extract entities from source files")
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

    args = parser.parse_args(argv)

    if args.command == "query":
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
    return [args.path, "--domain", args.domain, "--format", args.format]


if __name__ == "__main__":
    main()

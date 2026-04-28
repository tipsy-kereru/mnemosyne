"""
Unified extraction CLI.

Installed as ``mnemosyne-extract`` console_scripts entry point.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

EXTRACT_HELP = """\
Examples:
  mnemosyne-extract src/main.py
  mnemosyne-extract src/ --domain coding --format json
  mnemosyne-extract src/ --format wiki --scope-id session-1
  mnemosyne-extract src/ --source-channel vscode

Output:
  --format json  : Array of entity objects
      [{type, name, language, file_path, line_start, line_end,
        properties: {parameters, return_type, ...}, scope_id, source_channel}]
  --format wiki  : Markdown with [[wiki-links]] for knowledge graph integration
      Sections: Code Entities, Import Graph, Call Graph

Supported languages: Python, JavaScript, TypeScript, TSX, Go, Rust

Scope:
  --scope-id tags entities with a session/project identifier for scoped queries.
  --source-channel records the extraction source (vscode, cli, api, etc.).
"""


def main(argv=None):
    """Extraction CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mnemosyne-extract",
        description="Extract entities and relations from source files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXTRACT_HELP,
    )
    parser.add_argument("path", help="File or directory to extract from")
    parser.add_argument(
        "--domain",
        choices=["coding", "daily", "legal"],
        default="coding",
        help="Domain for extraction (default: coding)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "wiki"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--scope-id",
        help="Attach a scope ID (e.g. session name) to extracted entities",
    )
    parser.add_argument(
        "--source-channel", default="cli",
        help="Tag the extraction source channel (default: cli)",
    )
    parser.add_argument(
        "--examples", action="store_true",
        help="Show extraction examples and output format details",
    )

    args = parser.parse_args(argv)

    if args.examples:
        print(EXTRACT_HELP.strip())
        return

    path = Path(args.path)
    if not path.exists():
        parser.error(f"Path does not exist: {args.path}")

    if args.domain == "coding":
        from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor

        extractor = TreeSitterExtractor()
        if path.is_file():
            result = extractor.extract_file_full(
                path,
                scope_id=args.scope_id,
                source_channel=args.source_channel,
            )
            entities = result.entities
        else:
            entities = extractor.extract_directory(
                path,
                scope_id=args.scope_id,
                source_channel=args.source_channel,
            )
            result = None

        if args.format == "json":
            print(json.dumps([asdict(e) for e in entities], indent=2), file=sys.stdout)
        else:
            if result is not None:
                print(extractor.to_wiki_format(
                    entities,
                    imports=result.imports,
                    calls=result.calls,
                ), file=sys.stdout)
            else:
                print(extractor.to_wiki_format(entities), file=sys.stdout)
    else:
        print(f"Domain '{args.domain}' extraction is not yet implemented.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

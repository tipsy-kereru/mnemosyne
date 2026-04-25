"""
Unified extraction CLI.

Installed as ``mnemosyne-extract`` console_scripts entry point.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


def main(argv=None):
    """Extraction CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mnemosyne-extract",
        description="Extract entities and relations from source files",
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
    parser.add_argument("--scope-id", help="Attach a scope ID to extracted entities")
    parser.add_argument(
        "--source-channel", default="cli",
        help="Source channel tag (default: cli)",
    )

    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        parser.error(f"Path does not exist: {args.path}")

    if args.domain == "coding":
        from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor

        extractor = TreeSitterExtractor()
        if path.is_file():
            entities = extractor.extract_file(
                path,
                scope_id=args.scope_id,
                source_channel=args.source_channel,
            )
        else:
            entities = extractor.extract_directory(
                path,
                scope_id=args.scope_id,
                source_channel=args.source_channel,
            )

        if args.format == "json":
            print(json.dumps([asdict(e) for e in entities], indent=2))
        else:
            print(extractor.to_wiki_format(entities))
    else:
        print(f"Domain '{args.domain}' extraction is not yet implemented.")
        sys.exit(1)


if __name__ == "__main__":
    main()

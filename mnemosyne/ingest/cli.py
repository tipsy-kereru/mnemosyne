"""Standalone CLI for mnemosyne-add and mnemosyne-update."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from mnemosyne.ingest.ingester import Ingester, IngestResult, result_to_dict
from mnemosyne.ingest.update import Updater, stats_to_dict

logger = logging.getLogger(__name__)


_ADD_EXAMPLES = """\
Examples:
  # Ingest a single file into the daily domain
  mnemosyne-add path/to/notes.md --domain daily

  # Ingest a code project (auto-routes to coding domain per file)
  mnemosyne-add ~/projects/my-app --domain coding

  # Ingest an arxiv paper
  mnemosyne-add https://arxiv.org/abs/2401.00001 --domain coding

  # Ingest inline text
  mnemosyne-add --text "John works at Acme Corp" --domain daily

  # Scope ingestion to a session
  mnemosyne-add notes.md --scope-id session-1 --source-channel discord

  # Dry-run (show what would be extracted)
  mnemosyne-add notes.md --dry-run

  # Write the LLM Wiki somewhere other than ~/mnemosyne/wiki
  mnemosyne-add notes.md --wiki-root ./wiki

  # Opt in to bounded, redacted source excerpts in source pages
  mnemosyne-add notes.md --wiki-excerpts
"""


# @MX:ANCHOR: [AUTO] add_main is the public CLI entry for "mnemosyne add".
# @MX:REASON: Wired in pyproject.toml entry points; user-facing fan_in.
def _load_dotenv() -> None:
    try:
        from pathlib import Path
        from dotenv import load_dotenv  # type: ignore[import-not-found]
        current = Path(__file__).resolve().parent
        for _ in range(4):
            env_path = current / ".env"
            if env_path.exists():
                load_dotenv(dotenv_path=env_path)
                return
            current = current.parent
        load_dotenv()
    except ImportError:
        pass


def add_main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for ``mnemosyne-add``."""
    _load_dotenv()
    parser = argparse.ArgumentParser(
        prog="mnemosyne-add",
        description="Ingest a file, directory, URL, or inline text.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="File, directory, or URL to ingest. Omit when using --text.",
    )
    parser.add_argument("--text", help="Inline text to ingest (alternative to target).")
    parser.add_argument(
        "--domain",
        choices=("coding", "daily", "legal"),
        default="daily",
        help="Domain schema for extraction (default: daily).",
    )
    parser.add_argument("--scope-id", dest="scope_id", default=None)
    parser.add_argument(
        "--source-channel", dest="source_channel", default="cli"
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None, help="Override KnowledgeGraph DB path."
    )
    parser.add_argument(
        "--raw-root",
        dest="raw_root",
        default=None,
        help="Override mnemosyne raw root (default: ~/mnemosyne/raw/).",
    )
    parser.add_argument(
        "--wiki-root",
        dest="wiki_root",
        default=str(Path.home() / "mnemosyne" / "wiki"),
        help="Override LLM Wiki root (default: ~/mnemosyne/wiki/).",
    )
    parser.add_argument(
        "--no-wiki",
        action="store_true",
        help="Do not update Markdown LLM Wiki pages.",
    )
    parser.add_argument(
        "--wiki-excerpts",
        action="store_true",
        help="Opt in to bounded, redacted source excerpts in LLM Wiki source pages.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--examples", action="store_true", help="Show usage examples.")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args(argv)

    if args.examples:
        sys.stdout.write(_ADD_EXAMPLES)
        return 0

    _configure_logging(args.verbose)

    if not args.target and args.text is None:
        sys.stderr.write("error: provide a target or --text\n")
        return 2

    ingester = Ingester(
        db_path=Path(args.db_path) if args.db_path else None,
        raw_root=Path(args.raw_root) if args.raw_root else None,
        wiki_root=None if args.no_wiki else Path(args.wiki_root),
        include_wiki_excerpts=args.wiki_excerpts,
        dry_run=args.dry_run,
    )

    try:
        result = ingester.add(
            target=args.target or "",
            domain=args.domain,
            scope_id=args.scope_id,
            source_channel=args.source_channel,
            text=args.text,
        )
    except Exception as exc:  # noqa: BLE001 -- final-level CLI guard
        logger.exception("ingest failed")
        sys.stderr.write(f"error: {exc}\n")
        ingester.close()
        return 1

    ingester.close()
    sys.stdout.write(json.dumps(result_to_dict(result), indent=2) + "\n")
    return 0 if not result.errors else 1


_UPDATE_EXAMPLES = """\
Examples:
  # Update everything under ~/mnemosyne/raw/
  mnemosyne-update

  # Update a specific subtree
  mnemosyne-update ~/mnemosyne/raw/coding --domain coding

  # Show change stats only, do not extract
  mnemosyne-update --stats

  # Prune cache entries for files that no longer exist
  mnemosyne-update --prune

  # Update graph and LLM Wiki from a raw source subtree
  mnemosyne-update ~/mnemosyne/raw/daily --wiki-root ~/mnemosyne/wiki
"""


# @MX:ANCHOR: [AUTO] update_main is the public CLI entry for "mnemosyne update".
# @MX:REASON: Wired in pyproject.toml entry points; user-facing fan_in.
def update_main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for ``mnemosyne-update``."""
    _load_dotenv()
    parser = argparse.ArgumentParser(
        prog="mnemosyne-update",
        description="Re-extract changed files since the last ingestion.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Directory to scan (default: ~/mnemosyne/raw/).",
    )
    parser.add_argument(
        "--domain",
        choices=("coding", "daily", "legal", "auto"),
        default="auto",
        help="Domain to apply (default: auto, inferred from path).",
    )
    parser.add_argument("--scope-id", dest="scope_id", default=None)
    parser.add_argument("--source-channel", dest="source_channel", default="cli")
    parser.add_argument("--prune", action="store_true")
    parser.add_argument(
        "--stats", action="store_true", help="Show stats without updating."
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None, help="Override KnowledgeGraph DB path."
    )
    parser.add_argument(
        "--raw-root",
        dest="raw_root",
        default=None,
        help="Override mnemosyne raw root (default: ~/mnemosyne/raw/).",
    )
    parser.add_argument(
        "--wiki-root",
        dest="wiki_root",
        default=str(Path.home() / "mnemosyne" / "wiki"),
        help="Override LLM Wiki root (default: ~/mnemosyne/wiki/).",
    )
    parser.add_argument(
        "--no-wiki",
        action="store_true",
        help="Do not update Markdown LLM Wiki pages.",
    )
    parser.add_argument(
        "--wiki-excerpts",
        action="store_true",
        help="Opt in to bounded, redacted source excerpts in LLM Wiki source pages.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--examples", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args(argv)

    if args.examples:
        sys.stdout.write(_UPDATE_EXAMPLES)
        return 0

    _configure_logging(args.verbose)

    updater = Updater(
        db_path=Path(args.db_path) if args.db_path else None,
        raw_root=Path(args.raw_root) if args.raw_root else None,
        wiki_root=None if args.no_wiki else Path(args.wiki_root),
        include_wiki_excerpts=args.wiki_excerpts,
        dry_run=args.dry_run,
    )

    target_path = Path(args.path).expanduser() if args.path else None
    domain = None if args.domain == "auto" else args.domain

    try:
        if args.stats:
            stats = updater.stats_only(target_path)
        else:
            stats = updater.update(
                path=target_path,
                domain=domain,
                scope_id=args.scope_id,
                source_channel=args.source_channel,
                prune=args.prune,
            )
    except Exception as exc:  # noqa: BLE001 -- final-level CLI guard
        logger.exception("update failed")
        sys.stderr.write(f"error: {exc}\n")
        return 1

    sys.stdout.write(json.dumps(stats_to_dict(stats), indent=2) + "\n")
    return 0 if stats.errors == 0 else 1


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


# Re-export common types so external users can `from mnemosyne.ingest.cli import *`.
__all__ = [
    "IngestResult",
    "add_main",
    "result_to_dict",
    "stats_to_dict",
    "update_main",
]

"""Local JSON lifecycle API. No source reads, extraction, or remote authority."""

import json
import sqlite3
import sys
from pathlib import Path

from mnemosyne.graph.lifecycle import LifecycleError, LifecycleStore


def register_parser(subparsers):
    parser = subparsers.add_parser(
        "lifecycle", help="Apply versioned source evidence and approved user changes"
    )
    verbs = parser.add_subparsers(dest="lifecycle_command", required=True)
    for name in ("apply", "status", "inspect", "rebuild"):
        command = verbs.add_parser(name)
        command.add_argument("--db-path", required=True, help="Explicit target SQLite database")
        if name == "inspect":
            command.add_argument("target_kind", choices=["source", "entity", "relation"])
            command.add_argument("target_id")
        if name == "apply":
            command.add_argument("request", help="JSON request file, or - for stdin")
            command.add_argument(
                "--wiki-root", help="Rebuild wiki after graph commit; failure leaves wiki dirty"
            )
        if name == "rebuild":
            command.add_argument("--wiki-root", required=True)
        command.set_defaults(func=run, group="lifecycle")


def run(args):
    from mnemosyne.graph.knowledge_graph import KnowledgeGraph
    from mnemosyne.graph.lifecycle_wiki import rebuild_wiki

    kg = None
    try:
        request = None
        if args.lifecycle_command == "apply":
            text = (
                sys.stdin.read()
                if args.request == "-"
                else Path(args.request).read_text(encoding="utf-8")
            )
            request = json.loads(text)
        kg = KnowledgeGraph(str(Path(args.db_path).expanduser()))
        store = LifecycleStore(kg)
        if args.lifecycle_command == "status":
            result = store.status()
        elif args.lifecycle_command == "inspect":
            result = store.inspect(args.target_kind, args.target_id)
        elif args.lifecycle_command == "rebuild":
            result = rebuild_wiki(kg, Path(args.wiki_root))
        else:
            result = store.apply(request)
            if args.wiki_root:
                try:
                    result["wiki"] = rebuild_wiki(kg, Path(args.wiki_root))
                except (LifecycleError, OSError, RuntimeError, sqlite3.Error) as exc:
                    print(
                        json.dumps(
                            {
                                **result,
                                "graph_committed": True,
                                "wiki_dirty": True,
                                "wiki_error": str(exc),
                            },
                            ensure_ascii=False,
                        )
                    )
                    raise SystemExit(1) from exc
        print(json.dumps(result, ensure_ascii=False))
    except (LifecycleError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(
            json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    finally:
        if kg is not None:
            kg.close()

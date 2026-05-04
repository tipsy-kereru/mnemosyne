"""CLI helpers for maintaining the Mnemosyne Markdown LLM Wiki."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer, WikiLintReport, WikiLockError

_RESOLUTION_CHOICES = (
    "unresolved",
    "accepted_existing",
    "accepted_incoming",
    "superseded",
    "ambiguous",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mnemosyne wiki",
        description=(
            "Inspect and maintain the editor-neutral Markdown LLM Wiki layer. "
            "Use explicit --wiki-root paths for Joplin/Obsidian-style folders; "
            "no Joplin token is required."
        ),
    )
    subparsers = parser.add_subparsers(dest="wiki_command")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--wiki-root",
            default=str(Path.home() / "mnemosyne" / "wiki"),
            help="LLM Wiki root (default: ~/mnemosyne/wiki).",
        )
        p.add_argument("--db-path", default=None, help="KnowledgeGraph DB path.")
        p.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Output format (default: text).",
        )
        p.add_argument(
            "--lock-timeout",
            type=float,
            default=10.0,
            help="Seconds to wait for the wiki write lock on write commands (default: 10).",
        )

    status = subparsers.add_parser("status", help="Show read-only wiki health summary")
    add_common(status)

    lint = subparsers.add_parser("lint", help="Lint wiki links, metadata, and graph drift")
    add_common(lint)
    lint.add_argument("--strict", action="store_true", help="Exit nonzero on warnings too")

    contradictions = subparsers.add_parser(
        "contradictions",
        help="List graph-backed contradiction review items with stable conflict IDs",
    )
    add_common(contradictions)
    contradictions.add_argument("--all", action="store_true", help="Include resolved conflicts")

    resolve = subparsers.add_parser(
        "resolve",
        help="Update one conflict's resolution metadata without deleting evidence",
    )
    add_common(resolve)
    resolve.add_argument("conflict_id", help="Stable conflict ID from `mnemosyne wiki contradictions`")
    resolve.add_argument("--resolution", required=True, choices=_RESOLUTION_CHOICES)
    resolve.add_argument("--note", default=None, help="Optional review note to store on the conflict")
    resolve.add_argument("--reviewer", default=None, help="Optional reviewer label; no OS identity is collected by default")
    resolve.add_argument("--dry-run", action="store_true", help="Preview the metadata update without writing")

    prune = subparsers.add_parser(
        "prune",
        help="Plan stale wiki/graph reconciliation; no deletes are performed",
    )
    add_common(prune)
    prune.add_argument(
        "--apply-tombstones",
        action="store_true",
        help="Write tombstone records for stale candidates without deleting pages or graph facts",
    )

    semantic = subparsers.add_parser(
        "semantic-contradictions",
        help="Opt-in local semantic contradiction discovery; review candidates only",
    )
    add_common(semantic)
    semantic.add_argument(
        "--write",
        action="store_true",
        help="Persist candidates under review/ without mutating graph facts",
    )
    semantic.add_argument(
        "--include-raw-excerpts",
        action="store_true",
        help="Opt in to bounded redacted raw source excerpts for local files",
    )

    rebuild = subparsers.add_parser("rebuild", help="Regenerate generated wiki sections from graph data")
    add_common(rebuild)
    rebuild.add_argument("--dry-run", action="store_true", help="Show pages that would be written")

    doctor = subparsers.add_parser("doctor", help="Run status and lint together")
    add_common(doctor)
    doctor.add_argument("--strict", action="store_true", help="Exit nonzero on warnings too")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.wiki_command:
        parser.print_help()
        return 0

    maintainer = LLMWikiMaintainer(Path(args.wiki_root), lock_timeout=getattr(args, "lock_timeout", 10.0))
    db_path = Path(args.db_path).expanduser() if args.db_path else None

    if args.wiki_command == "status":
        payload = maintainer.status(db_path=db_path)
        _emit(payload, args.format)
        return 0

    if args.wiki_command == "lint":
        report = maintainer.lint(db_path=db_path)
        _emit_lint(report, args.format)
        return _lint_exit_code(report, strict=args.strict)

    if args.wiki_command == "contradictions":
        if db_path is None:
            sys.stderr.write("error: wiki contradictions requires --db-path\n")
            return 2
        payload = {
            "wiki_root": str(Path(args.wiki_root).expanduser()),
            "include_resolved": args.all,
            "items": maintainer.list_contradictions(db_path, include_resolved=args.all),
        }
        payload["count"] = len(payload["items"])
        _emit_contradictions(payload, args.format)
        return 0

    if args.wiki_command == "resolve":
        if db_path is None:
            sys.stderr.write("error: wiki resolve requires --db-path\n")
            return 2
        try:
            payload = maintainer.resolve_contradiction(
                db_path,
                conflict_id=args.conflict_id,
                resolution=args.resolution,
                note=args.note,
                reviewer=args.reviewer,
                dry_run=args.dry_run,
            )
        except KeyError as exc:
            _emit_error(str(exc), args.format)
            return 1
        except ValueError as exc:
            _emit_error(str(exc), args.format)
            return 2
        _emit_resolve(payload, args.format)
        return 0

    if args.wiki_command == "prune":
        if db_path is None:
            sys.stderr.write("error: wiki prune requires --db-path\n")
            return 2
        if args.apply_tombstones:
            try:
                payload = maintainer.write_tombstones(db_path)
            except WikiLockError as exc:
                _emit_lock_error(exc, args.format)
                return 1
        else:
            payload = maintainer.stale_plan(db_path)
        _emit(payload, args.format)
        return 0

    if args.wiki_command == "semantic-contradictions":
        if db_path is None:
            sys.stderr.write("error: wiki semantic-contradictions requires --db-path\n")
            return 2
        try:
            payload = maintainer.discover_semantic_contradictions(
                db_path,
                write=args.write,
                include_raw_excerpts=args.include_raw_excerpts,
            )
        except WikiLockError as exc:
            _emit_lock_error(exc, args.format)
            return 1
        _emit_semantic(payload, args.format)
        return 0

    if args.wiki_command == "rebuild":
        if db_path is None:
            sys.stderr.write("error: wiki rebuild requires --db-path\n")
            return 2
        try:
            update = maintainer.rebuild_from_graph(db_path, dry_run=args.dry_run)
        except WikiLockError as exc:
            _emit_lock_error(exc, args.format)
            return 1
        payload = {
            "wiki_root": str(Path(args.wiki_root).expanduser()),
            "dry_run": args.dry_run,
            "paths": [str(path) for path in update.paths],
            "count": len(update.paths),
        }
        _emit(payload, args.format)
        return 0

    if args.wiki_command == "doctor":
        status = maintainer.status(db_path=db_path)
        report = maintainer.lint(db_path=db_path)
        payload = {"status": status, "lint": report.to_dict()}
        _emit(payload, args.format)
        return _lint_exit_code(report, strict=args.strict)

    parser.print_help()
    return 2


def _emit_lock_error(exc: WikiLockError, fmt: str) -> None:
    payload = exc.to_dict()
    if fmt == "json":
        sys.stderr.write(json.dumps(payload, indent=2, default=str) + "\n")
    else:
        sys.stderr.write(f"error: {payload['message']}\n")
        sys.stderr.write(f"lock_path: {payload['lock_path']}\n")
        sys.stderr.write("retry: wait for the other writer to finish; inspect stale lock metadata before manual removal.\n")


def _emit(payload: dict[str, object], fmt: str) -> None:
    if fmt == "json":
        sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")
    else:
        for key, value in payload.items():
            sys.stdout.write(f"{key}: {value}\n")


def _emit_contradictions(payload: dict[str, Any], fmt: str) -> None:
    if fmt == "json":
        sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")
        return
    sys.stdout.write(f"count: {payload['count']}\n")
    for item in payload["items"]:
        sys.stdout.write(
            f"{item['conflict_id']} {item['entity_id']} {item['property_name']} "
            f"{item['resolution']} source={item['source_file']} "
            f"existing={item['existing']} incoming={item['incoming']}\n"
        )


def _emit_resolve(payload: dict[str, Any], fmt: str) -> None:
    if fmt == "json":
        sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")
        return
    action = "would update" if payload.get("dry_run") else "updated"
    sys.stdout.write(f"{action}: {payload['conflict_id']}\n")
    sys.stdout.write(f"entity_id: {payload['entity_id']}\n")
    sys.stdout.write(f"resolution: {payload['resolution']}\n")
    if payload.get("rebuild_required"):
        sys.stdout.write("rebuild_required: true\n")


def _emit_error(message: str, fmt: str) -> None:
    payload = {"ok": False, "error": message}
    if fmt == "json":
        sys.stderr.write(json.dumps(payload, indent=2, default=str) + "\n")
    else:
        sys.stderr.write(f"error: {message}\n")


def _emit_semantic(payload: dict[str, Any], fmt: str) -> None:
    if fmt == "json":
        sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")
        return
    sys.stdout.write(f"schema: {payload['schema']}\n")
    sys.stdout.write(f"processing_mode: {payload['processing_mode']}\n")
    sys.stdout.write(f"remote_model: {payload['remote_model']}\n")
    sys.stdout.write("candidate_wording: review candidates only; not truth judgments\n")
    sys.stdout.write(f"count: {payload['count']}\n")
    for item in payload.get("candidates") or []:
        sys.stdout.write(
            f"{item['candidate_id']} {item['subject_label']} "
            f"claim_type={item['claim_type']} confidence={item['confidence']} "
            f"uncertainty={item['uncertainty']}\n"
        )


def _emit_lint(report: WikiLintReport, fmt: str) -> None:
    if fmt == "json":
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
        return
    sys.stdout.write(f"ok: {report.ok}\n")
    sys.stdout.write(f"errors: {len(report.errors)}\n")
    for issue in report.errors:
        sys.stdout.write(f"ERROR {issue.code} {issue.path}: {issue.message}\n")
    sys.stdout.write(f"warnings: {len(report.warnings)}\n")
    for issue in report.warnings:
        sys.stdout.write(f"WARNING {issue.code} {issue.path}: {issue.message}\n")


def _lint_exit_code(report: WikiLintReport, *, strict: bool) -> int:
    if report.errors:
        return 1
    if strict and report.warnings:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

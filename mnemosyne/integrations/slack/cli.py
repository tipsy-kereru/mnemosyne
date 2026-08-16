"""``mnemosyne-slack`` — the manual entry point for Slack ingestion.

Contract §9. Every operation is invoked by hand: there is no scheduler,
watcher, launchd job, or event subscription anywhere in this package
(P4). Output is JSON on stdout, and every byte of it passes through
``redact`` first.

``query`` is the *only* read path that returns Slack content. The
knowledge graph's own query surfaces exclude ``work-slack`` — and in v1
they hold none of it to begin with (INV-1).

Exit codes (R34)::

    0  success
    1  unexpected error
    2  policy denial          (deny:*, slack_isolated, permission errors)
    3  credential problem     (missing token, over-permissioned token)
    4  target not found
    5  live Slack blocked     (expected in v1 — see §7.4)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from mnemosyne.integrations.slack.identity import source_id as build_source_id
from mnemosyne.integrations.slack.redact import redact

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_DENIED = 2
EXIT_CREDENTIAL = 3
EXIT_NOT_FOUND = 4
EXIT_LIVE_BLOCKED = 5

CONNECTOR_CHOICES = ("synthetic", "mock", "live")


def _emit(payload: dict[str, Any]) -> None:
    """Print JSON with redaction applied to the rendered text."""
    print(redact(json.dumps(payload, indent=2, default=str)))


def _load_fixture(path: Optional[str]) -> dict[str, Any]:
    if not path:
        raise FileNotFoundError(
            "--fixture is required for the synthetic and mock connectors"
        )
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _default_db_path() -> Path:
    from mnemosyne.graph.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph()
    try:
        return Path(kg.db_path)
    finally:
        kg.close()


def _store(args: argparse.Namespace):
    from mnemosyne.integrations.slack.store import SlackStore

    return SlackStore(args.db_path or _default_db_path())


# ── Connector construction ────────────────────────────────────────────

class _ConnectorSession:
    """Builds a connector and tears down the mock server afterwards."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.server = None

    def __enter__(self):
        from mnemosyne.integrations.slack.connector import SyntheticConnector

        kind = getattr(self.args, "connector", "synthetic")
        if kind == "synthetic":
            return SyntheticConnector(_load_fixture(self.args.fixture))

        from mnemosyne.integrations.slack.api import WebApiConnector
        from mnemosyne.integrations.slack.config import SlackConfig

        config = (
            SlackConfig.load(self.args.config)
            if getattr(self.args, "config", None)
            else SlackConfig()
        )

        if kind == "mock":
            from mnemosyne.integrations.slack.mock_api import MockSlackServer

            self.server = MockSlackServer(fixture=_load_fixture(self.args.fixture))
            self.server.start()
            return WebApiConnector(
                self.server.expected_token,
                base_url=self.server.base_url,
                max_retries=3,
                initial_backoff=0.01,
            )

        # live: resolve a real token, then refuse to use it (§7.4).
        token = config.resolve_token()
        return WebApiConnector(token, live_approved=False)

    def __exit__(self, *exc: Any) -> None:
        if self.server is not None:
            self.server.stop()
            self.server = None


# ── Commands ──────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    """Create the Slack tables and register every source in the config."""
    from mnemosyne.integrations.slack.config import SlackConfig

    store = _store(args)
    try:
        config = SlackConfig.load(args.config) if args.config else SlackConfig()
        registered = [
            store.register_source(
                s.team_id, s.channel_id, s.scope_id, acl_mode=s.acl_mode
            ).source_id
            for s in config.sources
        ]
        _emit({
            "db_path": store.db_path,
            "token_env": config.token_env,
            "registered": registered,
            "note": "no ACL check and no fetch happened; run `sync` for that",
        })
        return EXIT_OK
    finally:
        store.close()


def cmd_source_register(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        source = store.register_source(args.team_id, args.channel_id, args.scope_id)
        _emit({"source_id": source.source_id, "status": source.status})
        return EXIT_OK
    finally:
        store.close()


def cmd_source_list(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        _emit({"sources": [
            {
                "source_id": s.source_id,
                "scope_id": s.scope_id,
                "status": s.status,
                "channel_type": s.channel_type,
                "last_watermark": s.last_watermark,
                "last_sync_at": s.last_sync_at,
                "documents_processed": s.documents_processed,
            }
            for s in store.list_sources(status=args.status)
        ]})
        return EXIT_OK
    finally:
        store.close()


def cmd_source_revoke(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        changed = store.revoke_source(args.source_id, args.reason)
        if not changed and store.get_source(args.source_id) is None:
            _emit({"error": "deny:source_unregistered", "source_id": args.source_id})
            return EXIT_NOT_FOUND
        _emit({"source_id": args.source_id, "revoked": changed})
        return EXIT_OK
    finally:
        store.close()


def _run_sync(args: argparse.Namespace, reconcile: bool) -> int:
    from mnemosyne.integrations.slack.sync import SlackSyncEngine

    store = _store(args)
    try:
        with _ConnectorSession(args) as connector:
            engine = SlackSyncEngine(store, connector)
            result = (
                engine.reconcile(args.source_id, since=args.since, until=args.until)
                if reconcile
                else engine.sync(args.source_id, limit=args.limit)
            )
        payload = {
            "source_id": result.source_id,
            "total": result.total,
            "ingested": result.ingested,
            "updated": result.updated,
            "noop": result.noop,
            "tombstoned": result.tombstoned,
            "quarantined": result.quarantined,
            "rejected": result.rejected,
            "failed": result.failed,
            "watermark": result.watermark,
            "errors": result.errors,
        }
        _emit(payload)
        # A connector failure is now absorbed into the result rather than
        # raised, so the exit code has to carry it: an unusable run must
        # not look like a clean one.
        if result.quarantined:
            return EXIT_DENIED
        if result.failed:
            return EXIT_ERROR
        return EXIT_OK
    finally:
        store.close()


def cmd_sync(args: argparse.Namespace) -> int:
    return _run_sync(args, reconcile=False)


def cmd_reconcile(args: argparse.Namespace) -> int:
    return _run_sync(args, reconcile=True)


def cmd_status(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        sources = (
            [store.require_source(args.source_id)]
            if args.source_id
            else store.list_sources()
        )
        pending = len(store.list_quarantine())
        _emit({
            "quarantine_pending": pending,
            "sources": [
                {
                    "source_id": s.source_id,
                    "status": s.status,
                    "last_watermark": s.last_watermark,
                    "last_sync_at": s.last_sync_at,
                    "documents_processed": s.documents_processed,
                    "last_error": s.last_error,
                }
                for s in sources
            ],
        })
        return EXIT_OK
    finally:
        store.close()


def cmd_quarantine_list(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        _emit({"quarantine": [
            {
                "source_doc_id": r.source_doc_id,
                "source_id": r.source_id,
                "reason": r.reason,
                "quarantined_at": r.quarantined_at,
                "resolved": r.resolved,
                "resolution": r.resolution,
                "snapshot": r.snapshot,
            }
            for r in store.list_quarantine(resolved=args.resolved or False)
        ]})
        return EXIT_OK
    finally:
        store.close()


def cmd_quarantine_resolve(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        changed = store.resolve_quarantine(
            args.source_doc_id,
            args.source_id,
            actor=args.actor,
            resolution=args.resolution,
            reason=args.reason,
        )
        _emit({"resolved": changed, "source_doc_id": args.source_doc_id})
        return EXIT_OK if changed else EXIT_NOT_FOUND
    finally:
        store.close()


def cmd_query(args: argparse.Namespace) -> int:
    """The only read path that returns work-slack content (INV-2)."""
    store = _store(args)
    try:
        source = store.require_source(args.source_id)
        if source.status == "revoked":
            _emit({"error": "deny:source_revoked", "source_id": args.source_id})
            return EXIT_DENIED

        if args.grep:
            messages = store.search_messages(
                args.source_id,
                args.grep,
                include_tombstoned=args.include_tombstoned,
                limit=args.limit,
            )
        else:
            messages = store.list_messages(
                args.source_id,
                thread_ts=args.thread_ts,
                since=args.since or "",
                until=args.until or "",
                include_tombstoned=args.include_tombstoned,
                limit=args.limit,
            )

        payload: dict[str, Any] = {
            "source_id": source.source_id,
            "scope_id": source.scope_id,
            "count": len(messages),
            "results": [
                {
                    "message_key": m.message_key,
                    "thread_ts": m.thread_ts,
                    "ts": m.ts,
                    "user": m.user_id,
                    "text": m.text,
                    "version": m.version,
                    "edited_ts": m.edited_ts,
                    "tombstoned": m.tombstoned,
                }
                for m in messages
            ],
        }
        if args.thread_ts:
            root = store.get_message(
                build_source_id(source.team_id, source.channel_id)
                + f":{args.thread_ts}"
            )
            payload["thread_ts"] = args.thread_ts
            payload["thread_root_tombstoned"] = bool(root and root.tombstoned)
        _emit(payload)
        return EXIT_OK
    finally:
        store.close()


def cmd_purge(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        if not args.confirm:
            _emit({
                "error": "deny:confirmation_required",
                "hint": "purge permanently deletes stored messages; pass --confirm",
            })
            return EXIT_DENIED
        if store.get_source(args.source_id) is None:
            _emit({"error": "deny:source_unregistered", "source_id": args.source_id})
            return EXIT_NOT_FOUND
        removed = store.purge_source(args.source_id)
        _emit({"source_id": args.source_id, "rows_removed": removed})
        return EXIT_OK
    finally:
        store.close()


# ── Parser ────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mnemosyne-slack",
        description=(
            "Manual Slack ingestion into an isolated local store. "
            "Public channels only; live Slack access is blocked in this version."
        ),
    )
    parser.add_argument("--db-path", default=None, help="Knowledge graph DB path")
    parser.add_argument("--config", default=None, help="Slack config YAML path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create tables and register configured sources")
    p_init.set_defaults(func=cmd_init)

    p_source = sub.add_parser("source", help="Manage channel bindings")
    source_sub = p_source.add_subparsers(dest="source_command", required=True)

    p_reg = source_sub.add_parser("register", help="Bind a channel to a scope")
    p_reg.add_argument("--team-id", required=True)
    p_reg.add_argument("--channel-id", required=True)
    p_reg.add_argument("--scope-id", required=True)
    p_reg.set_defaults(func=cmd_source_register)

    p_list = source_sub.add_parser("list", help="List bindings")
    p_list.add_argument("--status", default=None)
    p_list.set_defaults(func=cmd_source_list)

    p_revoke = source_sub.add_parser("revoke", help="Stop reading a source")
    p_revoke.add_argument("--source-id", required=True)
    p_revoke.add_argument("--reason", required=True)
    p_revoke.set_defaults(func=cmd_source_revoke)

    p_sync = sub.add_parser("sync", help="Collect new messages from the checkpoint")
    p_sync.add_argument("--source-id", required=True)
    p_sync.add_argument("--connector", choices=CONNECTOR_CHOICES, default="synthetic")
    p_sync.add_argument("--fixture", default=None)
    p_sync.add_argument("--limit", type=int, default=200)
    p_sync.set_defaults(func=cmd_sync)

    p_rec = sub.add_parser(
        "reconcile", help="Diff a window against the remote (only tombstone path)"
    )
    p_rec.add_argument("--source-id", required=True)
    p_rec.add_argument("--since", required=True)
    p_rec.add_argument("--until", default="")
    p_rec.add_argument("--connector", choices=CONNECTOR_CHOICES, default="synthetic")
    p_rec.add_argument("--fixture", default=None)
    p_rec.add_argument("--limit", type=int, default=200)
    p_rec.set_defaults(func=cmd_reconcile)

    p_status = sub.add_parser("status", help="Checkpoints and quarantine counts")
    p_status.add_argument("--source-id", default=None)
    p_status.set_defaults(func=cmd_status)

    p_q = sub.add_parser("quarantine", help="Inspect and resolve quarantine")
    q_sub = p_q.add_subparsers(dest="quarantine_command", required=True)
    p_ql = q_sub.add_parser("list")
    p_ql.add_argument("--resolved", action="store_true")
    p_ql.set_defaults(func=cmd_quarantine_list)
    p_qr = q_sub.add_parser("resolve")
    p_qr.add_argument("--source-doc-id", required=True)
    p_qr.add_argument("--source-id", required=True)
    p_qr.add_argument("--actor", required=True)
    p_qr.add_argument("--resolution", required=True, choices=("replayed", "rejected"))
    p_qr.add_argument("--reason", required=True)
    p_qr.set_defaults(func=cmd_quarantine_resolve)

    p_query = sub.add_parser(
        "query", help="Read stored Slack content (the only path that returns it)"
    )
    p_query.add_argument("--source-id", required=True)
    p_query.add_argument("--thread-ts", default=None)
    p_query.add_argument("--grep", default=None)
    p_query.add_argument("--since", default=None)
    p_query.add_argument("--until", default=None)
    p_query.add_argument("--limit", type=int, default=200)
    p_query.add_argument("--include-tombstoned", action="store_true")
    p_query.set_defaults(func=cmd_query)

    p_purge = sub.add_parser("purge", help="Permanently delete a source's data")
    p_purge.add_argument("--source-id", required=True)
    p_purge.add_argument("--confirm", action="store_true")
    p_purge.set_defaults(func=cmd_purge)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    from mnemosyne.integrations.slack.api import (
        QUARANTINE_ERRORS,
        SlackApiError,
        SlackLiveBlocked,
    )
    from mnemosyne.integrations.slack.config import (
        SlackCredentialError,
        SlackScopeError,
    )
    from mnemosyne.integrations.slack.identity import SlackIdentityError
    from mnemosyne.integrations.slack.store import (
        DENY_SOURCE_UNREGISTERED,
        SlackStoreError,
    )

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SlackLiveBlocked as exc:
        _emit({
            "error": exc.code,
            "hint": "live Slack access needs human approval (gate-real-slack)",
        })
        return EXIT_LIVE_BLOCKED
    except (SlackCredentialError, SlackScopeError) as exc:
        _emit({"error": exc.code, "detail": str(exc)})
        return EXIT_CREDENTIAL
    except SlackApiError as exc:
        _emit({"error": exc.code, "detail": str(exc)})
        return EXIT_DENIED if exc.code in QUARANTINE_ERRORS else EXIT_ERROR
    except SlackStoreError as exc:
        _emit({"error": exc.code, "detail": str(exc)})
        if exc.code == DENY_SOURCE_UNREGISTERED:
            return EXIT_NOT_FOUND
        return EXIT_DENIED
    except SlackIdentityError as exc:
        _emit({"error": exc.code, "detail": str(exc)})
        return EXIT_DENIED
    except FileNotFoundError as exc:
        _emit({"error": "not_found", "detail": redact(str(exc))})
        return EXIT_NOT_FOUND


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

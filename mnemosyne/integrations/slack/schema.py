"""Slack table DDL, kept free of every heavier import.

``KnowledgeGraph._init_session_schema`` calls :func:`init_slack_schema`
on every open, so this module deliberately imports nothing beyond the
standard library — mirroring ``graph/longdoc_schema.py`` and
``query/chat_store.py``.

Contract R33: additive and idempotent only. No ``ALTER``, no backfill, no
change to graph-owned tables, and a failure here must not prevent the
knowledge graph from initializing.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS slack_source (
        source_id           TEXT PRIMARY KEY,
        team_id             TEXT NOT NULL,
        channel_id          TEXT NOT NULL,
        channel_type        TEXT NOT NULL DEFAULT '',
        scope_id            TEXT NOT NULL,
        status              TEXT NOT NULL DEFAULT 'registered',
        acl_mode            TEXT NOT NULL DEFAULT 'require_snapshot',
        acl_users           TEXT NOT NULL DEFAULT '[]',
        acl_captured_at     TEXT,
        is_private          INTEGER NOT NULL DEFAULT 0,
        is_ext_shared       INTEGER NOT NULL DEFAULT 0,
        is_org_shared       INTEGER NOT NULL DEFAULT 0,
        last_watermark      TEXT NOT NULL DEFAULT '',
        last_sync_at        TEXT,
        documents_processed INTEGER NOT NULL DEFAULT 0,
        last_error          TEXT NOT NULL DEFAULT '',
        registered_at       TEXT NOT NULL,
        revoked_at          TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_slack_source_scope ON slack_source(scope_id)",
    "CREATE INDEX IF NOT EXISTS idx_slack_source_status ON slack_source(status)",
    """
    CREATE TABLE IF NOT EXISTS slack_message (
        message_key      TEXT PRIMARY KEY,
        source_id        TEXT NOT NULL,
        thread_ts        TEXT NOT NULL,
        ts               TEXT NOT NULL,
        user_id          TEXT NOT NULL DEFAULT '',
        text             TEXT NOT NULL DEFAULT '',
        subtype          TEXT NOT NULL DEFAULT '',
        edited_ts        TEXT,
        content_hash     TEXT NOT NULL,
        version          INTEGER NOT NULL DEFAULT 1,
        first_seen_at    TEXT NOT NULL,
        updated_at       TEXT NOT NULL,
        tombstoned_at    TEXT,
        tombstone_reason TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_slack_msg_source ON slack_message(source_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_slack_msg_thread "
    "ON slack_message(source_id, thread_ts, ts)",
    """
    CREATE TABLE IF NOT EXISTS slack_quarantine (
        source_doc_id     TEXT NOT NULL,
        source_id         TEXT NOT NULL,
        reason            TEXT NOT NULL,
        quarantined_at    TEXT NOT NULL,
        snapshot_json     TEXT NOT NULL DEFAULT '{}',
        resolved          INTEGER NOT NULL DEFAULT 0,
        resolved_at       TEXT,
        resolved_by       TEXT,
        resolution        TEXT,
        resolution_reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (source_doc_id, source_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_slack_quarantine_source "
    "ON slack_quarantine(source_id)",
)


def init_slack_schema(conn: sqlite3.Connection) -> None:
    """Create the three Slack tables idempotently."""
    try:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.commit()
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        logger.error("Slack schema init failed: %s", exc)

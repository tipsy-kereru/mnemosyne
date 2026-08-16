"""SQLite persistence and lifecycle for the direct Slack integration.

Implements §2, §5.1, and §8.4 of
``docs/SLACK_INTEGRATION_CONTRACT.ko.md``.

Three tables live alongside the knowledge graph — ``slack_source``,
``slack_message``, ``slack_quarantine``. Slack content never reaches
``entities`` or ``relations`` (INV-1); that is what makes the read
surfaces this program cannot edit safe by construction.

Lifecycle rules enforced here and nowhere else (R5):

- a source must be ACL-verified before anything is fetched (R1)
- ``revoked`` is terminal (R3)
- ``quarantined`` is only left by an explicit human resolution (R4)
- deletion is a tombstone; the body is retained (R6). ``purge_source``
  is the single physical delete.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from mnemosyne.integrations.slack.acl import ChannelInfo, classify_channel, utc_now_iso
from mnemosyne.integrations.slack.identity import (
    SlackIdentityError,
    is_valid_ts,
    message_key_for_source,
    parse_source_id,
    require_ts,
)
from mnemosyne.integrations.slack.redact import redact
from mnemosyne.integrations.slack.schema import init_slack_schema

logger = logging.getLogger(__name__)

# ── Source states (§2.1) ──────────────────────────────────────────────
SOURCE_REGISTERED = "registered"
SOURCE_ACL_VERIFIED = "acl_verified"
SOURCE_ACTIVE = "active"
SOURCE_STALE = "stale"
SOURCE_QUARANTINED = "quarantined"
SOURCE_REVOKED = "revoked"

#: States from which a fetch is permitted (R1/R2/R3).
FETCHABLE_STATES = frozenset({SOURCE_ACL_VERIFIED, SOURCE_ACTIVE})

#: Allowed transitions. ``revoked`` is terminal.
_TRANSITIONS: dict[str, frozenset[str]] = {
    SOURCE_REGISTERED: frozenset(
        {SOURCE_ACL_VERIFIED, SOURCE_QUARANTINED, SOURCE_REVOKED}
    ),
    SOURCE_ACL_VERIFIED: frozenset(
        {SOURCE_ACTIVE, SOURCE_STALE, SOURCE_QUARANTINED, SOURCE_REVOKED}
    ),
    SOURCE_ACTIVE: frozenset(
        {SOURCE_ACTIVE, SOURCE_STALE, SOURCE_QUARANTINED, SOURCE_REVOKED}
    ),
    SOURCE_STALE: frozenset(
        {SOURCE_ACL_VERIFIED, SOURCE_QUARANTINED, SOURCE_REVOKED}
    ),
    SOURCE_QUARANTINED: frozenset({SOURCE_REGISTERED, SOURCE_REVOKED}),
    SOURCE_REVOKED: frozenset(),
}

# ── Upsert outcomes (§2.2) ────────────────────────────────────────────
UPSERT_INSERTED = "inserted"
UPSERT_UPDATED = "updated"
UPSERT_NOOP = "noop"

TOMBSTONED = "tombstoned"
TOMBSTONED_NOOP = "tombstoned_noop"
NOT_FOUND = "not_found"

# ── Rejection codes (§10) ─────────────────────────────────────────────
REJECT_TOMBSTONED = "reject:tombstoned_source"
REJECT_IDENTITY = "reject:identity_mismatch"
REJECT_INVALID_TS = "reject:invalid_ts"
DENY_SOURCE_UNREGISTERED = "deny:source_unregistered"
DENY_SOURCE_REVOKED = "deny:source_revoked"

RESOLUTION_REPLAYED = "replayed"
RESOLUTION_REJECTED = "rejected"


class SlackStoreError(Exception):
    """Carries a contract denial/rejection code (§10)."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(redact(message or code))


@dataclass
class SlackSource:
    source_id: str
    team_id: str
    channel_id: str
    scope_id: str
    channel_type: str = ""
    status: str = SOURCE_REGISTERED
    acl_mode: str = "require_snapshot"
    acl_users: list[str] = field(default_factory=list)
    acl_captured_at: Optional[str] = None
    is_private: bool = False
    is_ext_shared: bool = False
    is_org_shared: bool = False
    last_watermark: str = ""
    last_sync_at: Optional[str] = None
    documents_processed: int = 0
    last_error: str = ""
    registered_at: str = ""
    revoked_at: Optional[str] = None

    def channel_info(self) -> ChannelInfo:
        """Rebuild the ACL view stored for this source."""
        return ChannelInfo(
            channel_id=self.channel_id,
            is_private=self.is_private,
            is_ext_shared=self.is_ext_shared,
            is_org_shared=self.is_org_shared,
            members=list(self.acl_users),
            captured_at=self.acl_captured_at,
        )


@dataclass
class SlackMessage:
    message_key: str
    source_id: str
    thread_ts: str
    ts: str
    content_hash: str
    user_id: str = ""
    text: str = ""
    subtype: str = ""
    edited_ts: Optional[str] = None
    version: int = 1
    first_seen_at: str = ""
    updated_at: str = ""
    tombstoned_at: Optional[str] = None
    tombstone_reason: str = ""

    @property
    def tombstoned(self) -> bool:
        return bool(self.tombstoned_at)


@dataclass
class SlackQuarantineRecord:
    source_doc_id: str
    source_id: str
    reason: str
    quarantined_at: str = ""
    snapshot: dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution: Optional[str] = None
    resolution_reason: str = ""


class SlackStore:
    """Owns every write to the ``slack_*`` tables."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        init_slack_schema(self.conn)

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, timeout=30.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    # ── Sources ───────────────────────────────────────────────────────

    def register_source(
        self,
        team_id: str,
        channel_id: str,
        scope_id: str,
        *,
        acl_mode: str = "require_snapshot",
    ) -> SlackSource:
        """Register a ``(team, channel) → scope`` binding (D3).

        No ACL check and no fetch happen here; the source starts in
        ``registered`` and cannot be read until §4.1 runs.
        """
        if not scope_id:
            raise SlackStoreError("deny:scope_mismatch", "scope_id is required")
        if acl_mode != "require_snapshot":
            raise SlackStoreError(
                "deny:acl_missing",
                f"unsupported acl_mode {acl_mode!r}; v1 supports require_snapshot",
            )
        from mnemosyne.integrations.slack.identity import source_id as build_source_id

        sid = build_source_id(team_id, channel_id)
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO slack_source
                (source_id, team_id, channel_id, scope_id, status, acl_mode,
                 registered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                scope_id = excluded.scope_id
            """,
            (sid, team_id, channel_id, scope_id, SOURCE_REGISTERED, acl_mode, now),
        )
        self.conn.commit()
        source = self.get_source(sid)
        assert source is not None
        return source

    def get_source(self, source_id: str) -> Optional[SlackSource]:
        row = self.conn.execute(
            "SELECT * FROM slack_source WHERE source_id = ?", (source_id,)
        ).fetchone()
        return _row_to_source(row) if row is not None else None

    def require_source(self, source_id: str) -> SlackSource:
        source = self.get_source(source_id)
        if source is None:
            raise SlackStoreError(
                DENY_SOURCE_UNREGISTERED, f"unknown source {source_id}"
            )
        return source

    def list_sources(self, *, status: Optional[str] = None) -> list[SlackSource]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM slack_source WHERE status = ? ORDER BY source_id",
                (status,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM slack_source ORDER BY source_id"
            ).fetchall()
        return [_row_to_source(r) for r in rows]

    def set_status(
        self, source_id: str, status: str, *, error: Optional[str] = None
    ) -> SlackSource:
        """Apply a lifecycle transition, refusing illegal ones (R5).

        ``error`` is only written when supplied — a plain transition must
        not erase the reason a previous run recorded.
        """
        source = self.require_source(source_id)
        allowed = _TRANSITIONS.get(source.status, frozenset())
        if status != source.status and status not in allowed:
            raise SlackStoreError(
                "deny:invalid_transition",
                f"{source.status} -> {status} is not a permitted transition",
            )
        if error is None:
            self.conn.execute(
                "UPDATE slack_source SET status = ? WHERE source_id = ?",
                (status, source_id),
            )
        else:
            self.conn.execute(
                "UPDATE slack_source SET status = ?, last_error = ? "
                "WHERE source_id = ?",
                (status, redact(error), source_id),
            )
        self.conn.commit()
        return self.require_source(source_id)

    def record_acl(self, source_id: str, info: ChannelInfo) -> SlackSource:
        """Persist the ACL snapshot and move the source to ``acl_verified``.

        Only user IDs and a capture time are stored (R16).
        """
        source = self.require_source(source_id)
        if source.status == SOURCE_REVOKED:
            raise SlackStoreError(DENY_SOURCE_REVOKED, f"{source_id} is revoked")
        self.conn.execute(
            """
            UPDATE slack_source SET
                channel_type    = ?,
                acl_users       = ?,
                acl_captured_at = ?,
                is_private      = ?,
                is_ext_shared   = ?,
                is_org_shared   = ?
            WHERE source_id = ?
            """,
            (
                classify_channel(info),
                json.dumps(list(info.members)),
                info.captured_at,
                int(info.is_private),
                int(info.is_ext_shared),
                int(info.is_org_shared),
                source_id,
            ),
        )
        self.conn.commit()
        if source.status in (SOURCE_REGISTERED, SOURCE_STALE):
            return self.set_status(source_id, SOURCE_ACL_VERIFIED)
        return self.require_source(source_id)

    def revoke_source(self, source_id: str, reason: str) -> bool:
        """Terminal state. Stored messages are kept; only ``purge`` deletes."""
        source = self.get_source(source_id)
        if source is None:
            return False
        if source.status == SOURCE_REVOKED:
            return False
        self.set_status(source_id, SOURCE_REVOKED, error=reason)
        self.conn.execute(
            "UPDATE slack_source SET revoked_at = ? WHERE source_id = ?",
            (utc_now_iso(), source_id),
        )
        self.conn.commit()
        return True

    # ── Messages ──────────────────────────────────────────────────────

    def get_message(self, message_key: str) -> Optional[SlackMessage]:
        row = self.conn.execute(
            "SELECT * FROM slack_message WHERE message_key = ?", (message_key,)
        ).fetchone()
        return _row_to_message(row) if row is not None else None

    def upsert_message(self, msg: SlackMessage) -> str:
        """Insert, update, or no-op one message.

        Idempotent by construction: the same body yields the same
        ``content_hash`` and therefore ``noop`` (R10/R21). An edit bumps
        ``version``. A tombstoned key never silently returns (R6).
        """
        if not is_valid_ts(msg.ts):
            raise SlackStoreError(REJECT_INVALID_TS, f"invalid ts {msg.ts!r}")
        if not is_valid_ts(msg.thread_ts):
            raise SlackStoreError(
                REJECT_INVALID_TS, f"invalid thread_ts {msg.thread_ts!r}"
            )
        try:
            expected_key = message_key_for_source(msg.source_id, msg.ts)
        except SlackIdentityError as exc:
            raise SlackStoreError(REJECT_IDENTITY, str(exc)) from exc
        if msg.message_key != expected_key:
            raise SlackStoreError(
                REJECT_IDENTITY,
                f"message_key does not match its source_id and ts: {msg.message_key}",
            )

        existing = self.get_message(msg.message_key)
        now = utc_now_iso()

        if existing is None:
            self.conn.execute(
                """
                INSERT INTO slack_message
                    (message_key, source_id, thread_ts, ts, user_id, text,
                     subtype, edited_ts, content_hash, version,
                     first_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    msg.message_key, msg.source_id, msg.thread_ts, msg.ts,
                    msg.user_id, msg.text, msg.subtype, msg.edited_ts,
                    msg.content_hash, now, now,
                ),
            )
            self.conn.commit()
            return UPSERT_INSERTED

        if existing.tombstoned_at:
            # A deleted message must not be resurrected by a later poll.
            raise SlackStoreError(
                REJECT_TOMBSTONED,
                f"{msg.message_key} is tombstoned; explicit reinstatement required",
            )

        if (
            existing.content_hash == msg.content_hash
            and (existing.edited_ts or "") == (msg.edited_ts or "")
        ):
            return UPSERT_NOOP

        self.conn.execute(
            """
            UPDATE slack_message SET
                thread_ts = ?, user_id = ?, text = ?, subtype = ?,
                edited_ts = ?, content_hash = ?, version = version + 1,
                updated_at = ?
            WHERE message_key = ?
            """,
            (
                msg.thread_ts, msg.user_id, msg.text, msg.subtype,
                msg.edited_ts, msg.content_hash, now, msg.message_key,
            ),
        )
        self.conn.commit()
        return UPSERT_UPDATED

    def tombstone_message(self, message_key: str, reason: str) -> str:
        """Mark a message deleted without removing its body (R6). Idempotent."""
        existing = self.get_message(message_key)
        if existing is None:
            return NOT_FOUND
        if existing.tombstoned_at:
            return TOMBSTONED_NOOP
        now = utc_now_iso()
        self.conn.execute(
            "UPDATE slack_message SET tombstoned_at = ?, tombstone_reason = ?, "
            "updated_at = ? WHERE message_key = ?",
            (now, reason, now, message_key),
        )
        self.conn.commit()
        return TOMBSTONED

    def list_messages(
        self,
        source_id: str,
        *,
        thread_ts: Optional[str] = None,
        since: str = "",
        until: str = "",
        include_tombstoned: bool = False,
        limit: int = 200,
    ) -> list[SlackMessage]:
        """Messages in ``ts`` order.

        ``since``/``until`` are inclusive and compared as strings, which
        equals numeric order for validated timestamps (R9).
        """
        clauses = ["source_id = ?"]
        params: list[Any] = [source_id]
        if thread_ts is not None:
            clauses.append("thread_ts = ?")
            params.append(require_ts(thread_ts))
        if since:
            clauses.append("ts >= ?")
            params.append(require_ts(since))
        if until:
            clauses.append("ts <= ?")
            params.append(require_ts(until))
        if not include_tombstoned:
            clauses.append("tombstoned_at IS NULL")
        rows = self.conn.execute(
            f"SELECT * FROM slack_message WHERE {' AND '.join(clauses)} "
            f"ORDER BY ts ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_row_to_message(r) for r in rows]

    def search_messages(
        self,
        source_id: Optional[str],
        term: str,
        *,
        include_tombstoned: bool = False,
        limit: int = 50,
    ) -> list[SlackMessage]:
        """Substring search inside the isolated Slack store only.

        Deliberately a ``LIKE`` scan: no FTS virtual table is added for
        Slack content (contract §12 item 14).
        """
        clauses = ["m.text LIKE ?"]
        params: list[Any] = [f"%{term}%"]
        if source_id:
            clauses.append("m.source_id = ?")
            params.append(source_id)
        else:
            # Revoked sources are never searchable (R3).
            clauses.append(
                "m.source_id IN (SELECT source_id FROM slack_source "
                "WHERE status != ?)"
            )
            params.append(SOURCE_REVOKED)
        if not include_tombstoned:
            clauses.append("m.tombstoned_at IS NULL")
        rows = self.conn.execute(
            f"SELECT m.* FROM slack_message m WHERE {' AND '.join(clauses)} "
            f"ORDER BY m.ts ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_row_to_message(r) for r in rows]

    # ── Checkpoint (§5.1) ─────────────────────────────────────────────

    def save_checkpoint(
        self, source_id: str, watermark: str, processed: int
    ) -> SlackSource:
        """Advance the watermark. Monotonic: never moves backwards (R18)."""
        source = self.require_source(source_id)
        if watermark and not is_valid_ts(watermark):
            raise SlackStoreError(
                REJECT_INVALID_TS, f"invalid watermark {watermark!r}"
            )
        new_watermark = max(watermark, source.last_watermark)
        self.conn.execute(
            "UPDATE slack_source SET last_watermark = ?, last_sync_at = ?, "
            "documents_processed = ?, last_error = '' WHERE source_id = ?",
            (new_watermark, utc_now_iso(), processed, source_id),
        )
        self.conn.commit()
        return self.require_source(source_id)

    def record_error(self, source_id: str, error: str) -> None:
        """Record a failure without moving the watermark (R20)."""
        self.conn.execute(
            "UPDATE slack_source SET last_error = ?, last_sync_at = ? "
            "WHERE source_id = ?",
            (redact(error), utc_now_iso(), source_id),
        )
        self.conn.commit()

    # ── Quarantine (§4.4) ─────────────────────────────────────────────

    def quarantine(
        self,
        source_id: str,
        source_doc_id: str,
        reason: str,
        snapshot: Optional[dict[str, Any]] = None,
    ) -> SlackQuarantineRecord:
        """Hold a source or document pending human resolution (R17).

        ``snapshot`` is metadata only; this method refuses anything
        carrying a message body or a token (R16).
        """
        payload = dict(snapshot or {})
        _assert_snapshot_safe(payload)
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO slack_quarantine
                (source_doc_id, source_id, reason, quarantined_at, snapshot_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_doc_id, source_id) DO UPDATE SET
                reason         = excluded.reason,
                quarantined_at = excluded.quarantined_at,
                snapshot_json  = excluded.snapshot_json,
                resolved       = 0,
                resolved_at    = NULL,
                resolved_by    = NULL,
                resolution     = NULL,
                resolution_reason = ''
            """,
            (source_doc_id, source_id, reason, now, json.dumps(payload)),
        )
        self.conn.commit()
        source = self.get_source(source_id)
        if source is not None and source.status not in (
            SOURCE_QUARANTINED, SOURCE_REVOKED
        ):
            self.set_status(source_id, SOURCE_QUARANTINED, error=reason)
        return SlackQuarantineRecord(
            source_doc_id=source_doc_id,
            source_id=source_id,
            reason=reason,
            quarantined_at=now,
            snapshot=payload,
        )

    def list_quarantine(
        self, *, resolved: Optional[bool] = False
    ) -> list[SlackQuarantineRecord]:
        if resolved is None:
            rows = self.conn.execute(
                "SELECT * FROM slack_quarantine ORDER BY quarantined_at"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM slack_quarantine WHERE resolved = ? "
                "ORDER BY quarantined_at",
                (int(resolved),),
            ).fetchall()
        return [_row_to_quarantine(r) for r in rows]

    def resolve_quarantine(
        self,
        source_doc_id: str,
        source_id: str,
        *,
        actor: str,
        resolution: str,
        reason: str,
    ) -> bool:
        """Human-only resolution (R17). No automatic replay exists.

        ``replayed`` returns the source to ``registered`` so the next
        sync re-runs the ACL gate from scratch. ``rejected`` marks the
        record handled but leaves the source quarantined.
        """
        if resolution not in (RESOLUTION_REPLAYED, RESOLUTION_REJECTED):
            raise SlackStoreError(
                "deny:invalid_resolution",
                f"resolution must be {RESOLUTION_REPLAYED} or {RESOLUTION_REJECTED}",
            )
        if not actor.strip():
            raise SlackStoreError("deny:actor_required", "actor is required")
        cursor = self.conn.execute(
            "UPDATE slack_quarantine SET resolved = 1, resolved_at = ?, "
            "resolved_by = ?, resolution = ?, resolution_reason = ? "
            "WHERE source_doc_id = ? AND source_id = ? AND resolved = 0",
            (utc_now_iso(), actor, resolution, reason, source_doc_id, source_id),
        )
        self.conn.commit()
        if cursor.rowcount == 0:
            return False
        source = self.get_source(source_id)
        if (
            resolution == RESOLUTION_REPLAYED
            and source is not None
            and source.status == SOURCE_QUARANTINED
        ):
            self.set_status(source_id, SOURCE_REGISTERED)
        return True

    # ── Explicit destruction ──────────────────────────────────────────

    def purge_source(self, source_id: str) -> int:
        """The only physical delete in this package. Returns rows removed."""
        removed = 0
        for table in ("slack_message", "slack_quarantine", "slack_source"):
            cursor = self.conn.execute(
                f"DELETE FROM {table} WHERE source_id = ?", (source_id,)
            )
            removed += cursor.rowcount or 0
        self.conn.commit()
        return removed

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ── Row mapping ───────────────────────────────────────────────────────

#: Keys a quarantine snapshot may carry (R16). Everything else is a leak.
_ALLOWED_SNAPSHOT_KEYS = frozenset({
    "source_id", "team_id", "channel_id", "channel_type", "is_private",
    "is_ext_shared", "is_org_shared", "member_count", "captured_at", "reason",
})


def _assert_snapshot_safe(snapshot: dict[str, Any]) -> None:
    """Refuse a quarantine snapshot carrying message content (R16)."""
    unexpected = sorted(set(snapshot) - _ALLOWED_SNAPSHOT_KEYS)
    if unexpected:
        raise SlackStoreError(
            "reject:quarantine_payload",
            f"quarantine snapshot may not carry {unexpected}",
        )
    for key, value in snapshot.items():
        if isinstance(value, str) and redact(value) != value:
            raise SlackStoreError(
                "reject:quarantine_payload",
                f"quarantine snapshot field {key!r} looks token-shaped",
            )


def _row_to_source(row: sqlite3.Row) -> SlackSource:
    try:
        acl_users = json.loads(row["acl_users"] or "[]")
    except (ValueError, TypeError):
        acl_users = []
    return SlackSource(
        source_id=row["source_id"],
        team_id=row["team_id"],
        channel_id=row["channel_id"],
        scope_id=row["scope_id"],
        channel_type=row["channel_type"],
        status=row["status"],
        acl_mode=row["acl_mode"],
        acl_users=acl_users,
        acl_captured_at=row["acl_captured_at"],
        is_private=bool(row["is_private"]),
        is_ext_shared=bool(row["is_ext_shared"]),
        is_org_shared=bool(row["is_org_shared"]),
        last_watermark=row["last_watermark"],
        last_sync_at=row["last_sync_at"],
        documents_processed=row["documents_processed"],
        last_error=row["last_error"],
        registered_at=row["registered_at"],
        revoked_at=row["revoked_at"],
    )


def _row_to_message(row: sqlite3.Row) -> SlackMessage:
    return SlackMessage(
        message_key=row["message_key"],
        source_id=row["source_id"],
        thread_ts=row["thread_ts"],
        ts=row["ts"],
        user_id=row["user_id"],
        text=row["text"],
        subtype=row["subtype"],
        edited_ts=row["edited_ts"],
        content_hash=row["content_hash"],
        version=row["version"],
        first_seen_at=row["first_seen_at"],
        updated_at=row["updated_at"],
        tombstoned_at=row["tombstoned_at"],
        tombstone_reason=row["tombstone_reason"],
    )


def _row_to_quarantine(row: sqlite3.Row) -> SlackQuarantineRecord:
    try:
        snapshot = json.loads(row["snapshot_json"] or "{}")
    except (ValueError, TypeError):
        snapshot = {}
    return SlackQuarantineRecord(
        source_doc_id=row["source_doc_id"],
        source_id=row["source_id"],
        reason=row["reason"],
        quarantined_at=row["quarantined_at"],
        snapshot=snapshot,
        resolved=bool(row["resolved"]),
        resolved_at=row["resolved_at"],
        resolved_by=row["resolved_by"],
        resolution=row["resolution"],
        resolution_reason=row["resolution_reason"],
    )


def parse_source(source_id_value: str) -> tuple[str, str]:
    """Re-export for callers that only import the store."""
    return parse_source_id(source_id_value)

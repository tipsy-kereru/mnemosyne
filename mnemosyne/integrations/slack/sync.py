"""Manual sync and reconcile for the direct Slack integration.

Implements §4.1 and §5 of ``docs/SLACK_INTEGRATION_CONTRACT.ko.md``.

Two operations, both invoked by hand — there is no scheduler, watcher, or
event subscription anywhere in this package (P4):

``sync``
    Incremental collection from the checkpoint forward. Never creates a
    tombstone: ``conversations.history`` does not report deletions, so
    inferring one from its output would be guesswork (R22).

``reconcile``
    Re-enumerates a bounded window and diffs it against local state. The
    only path that tombstones. A partial remote response aborts the whole
    reconcile rather than mistaking a truncated page for a deletion (R24).

Because ``sync`` only asks for messages newer than the checkpoint, an
edit to an already-collected message is invisible to it — the same
limitation that makes deletions reconcile-only. Both are picked up by
``reconcile`` over a window that covers the edited message.

The watermark never moves past an unresolved item (R18), so a rejected or
quarantined message is retried on the next run instead of being skipped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from mnemosyne.integrations.slack.acl import (
    ChannelInfo,
    acl_denial,
    quarantine_snapshot,
    utc_now,
    utc_now_iso,
)
from mnemosyne.integrations.slack.connector import FetchedMessage, SlackConnector
from mnemosyne.integrations.slack.identity import (
    SlackIdentityError,
    is_valid_ts,
    message_hash,
    message_key_for_source,
)
from mnemosyne.integrations.slack.redact import redact
from mnemosyne.integrations.slack.store import (
    SOURCE_ACTIVE,
    SOURCE_QUARANTINED,
    SOURCE_REVOKED,
    SlackMessage,
    SlackStore,
    SlackStoreError,
    TOMBSTONED,
    UPSERT_INSERTED,
    UPSERT_NOOP,
    UPSERT_UPDATED,
)

logger = logging.getLogger(__name__)

STATUS_INGESTED = "ingested"
STATUS_UPDATED = "updated"
STATUS_NOOP = "noop"
STATUS_TOMBSTONED = "tombstoned"
STATUS_QUARANTINED = "quarantined"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"

DENY_SOURCE_QUARANTINED = "deny:source_quarantined"
DENY_SOURCE_REVOKED = "deny:source_revoked"
RECONCILE_REMOTE_ABSENT = "reconcile:remote_absent"
RECONCILE_MALFORMED_REMOTE = "reconcile:malformed_remote_ts"

#: Connector error codes that mean the channel must be quarantined rather
#: than retried (§10). Matched duck-typed on ``exc.code`` so this module
#: stays free of the HTTP adapter's imports and works for any connector.
QUARANTINE_API_ERRORS = frozenset({
    "not_in_channel",
    "channel_not_found",
    "is_archived",
    "restricted_action",
})

#: Upper bound on a single manual enumeration.
MAX_WINDOW = 10_000


@dataclass
class SyncResult:
    source_id: str
    total: int = 0
    ingested: int = 0
    updated: int = 0
    noop: int = 0
    tombstoned: int = 0
    quarantined: int = 0
    rejected: int = 0
    failed: int = 0
    watermark: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def unresolved_count(self) -> int:
        return self.quarantined + self.rejected + self.failed


def safe_watermark(
    committed: list[str], unresolved: list[str], previous: str
) -> str:
    """Advance only to just before the earliest unresolved item (R18).

    Monotonic: the result is never earlier than ``previous``. All inputs
    must already be R8-validated, which is what makes string comparison
    equal to numeric comparison (R9).
    """
    if unresolved:
        blocker = min(unresolved)
        reachable = [ts for ts in committed if ts < blocker]
    else:
        reachable = list(committed)
    candidate = max(reachable) if reachable else previous
    return max(candidate, previous or "")


class SlackSyncEngine:
    """Drives one source through the ACL gate and into the store."""

    def __init__(
        self,
        store: SlackStore,
        connector: SlackConnector,
        *,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.store = store
        self.connector = connector
        self._now = now or utc_now

    # ── Gate (§4.1) ───────────────────────────────────────────────────

    def _check_state(self, source_id: str) -> str:
        """Return a denial code when the source may not be read at all."""
        source = self.store.require_source(source_id)
        if source.status == SOURCE_REVOKED:
            return DENY_SOURCE_REVOKED
        if source.status == SOURCE_QUARANTINED:
            return DENY_SOURCE_QUARANTINED
        return ""

    def _acl_gate(self, source_id: str) -> tuple[Optional[ChannelInfo], str]:
        """Steps 2-5 of R12: inspect, judge, and only then permit a fetch.

        Returns ``(info, denial)``. When ``denial`` is non-empty the
        caller must not touch ``history``/``replies``.
        """
        source = self.store.require_source(source_id)
        info = self.connector.channel_info(source.channel_id)
        if not info.captured_at:
            info.captured_at = utc_now_iso()
        denial = acl_denial(info, now=self._now())
        if denial:
            return info, denial
        self.store.record_acl(source_id, info)
        return info, ""

    def _run_gate(
        self, source_id: str, result: SyncResult
    ) -> tuple[Optional[ChannelInfo], bool]:
        """Run the ACL gate, converting connector failures into state.

        Returns ``(info, may_fetch)``. A failure here means access was
        never verified, so ``may_fetch`` is False and the caller must not
        touch ``history``/``replies`` (R12).

        Errors are matched on ``exc.code`` rather than on an exception
        class, so this module does not import the HTTP adapter and any
        connector implementation can participate. Three outcomes:

        - ``blocked:*`` / ``reject:*`` and ``SlackStoreError`` describe
          *our own* refusal to act — a blocked live call, a missing or
          over-permissioned token, an unregistered source. They propagate
          so the CLI can report them with their own exit code; turning
          them into a quarantine record would blame the channel for an
          operator-side problem.
        - Codes in :data:`QUARANTINE_API_ERRORS` describe the channel's
          condition and quarantine it (§10).
        - Anything else is a run failure: recorded, counted, no fetch.
        """
        try:
            info, denial = self._acl_gate(source_id)
        except SlackStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 - unverified access must not fetch
            code = getattr(exc, "code", "") or (
                "channel_not_found" if isinstance(exc, LookupError) else ""
            )
            if code.startswith(("blocked:", "reject:")):
                raise
            message = redact(str(exc)) or code or exc.__class__.__name__
            if code in QUARANTINE_API_ERRORS:
                self._quarantine(source_id, None, code)
                result.quarantined += 1
                result.errors.append(code)
            else:
                logger.warning("Slack ACL check failed: %s", message)
                self.store.record_error(source_id, message)
                result.failed += 1
                result.errors.append(code or message)
            result.watermark = self.store.require_source(source_id).last_watermark
            return None, False

        if denial:
            self._quarantine(source_id, info, denial)
            result.quarantined += 1
            result.errors.append(denial)
            result.watermark = self.store.require_source(source_id).last_watermark
            return info, False

        return info, True

    def _quarantine(
        self, source_id: str, info: Optional[ChannelInfo], reason: str
    ) -> None:
        source = self.store.require_source(source_id)
        snapshot = (
            quarantine_snapshot(info, source_id, source.team_id)
            if info is not None
            else {"source_id": source_id, "team_id": source.team_id}
        )
        snapshot["reason"] = reason
        self.store.quarantine(source_id, source_id, f"quarantine:{reason}", snapshot)

    # ── Message handling ──────────────────────────────────────────────

    def _to_message(self, source_id: str, fetched: FetchedMessage) -> SlackMessage:
        ts = fetched.ts
        thread_ts = fetched.resolved_thread_ts()
        return SlackMessage(
            message_key=message_key_for_source(source_id, ts),
            source_id=source_id,
            thread_ts=thread_ts,
            ts=ts,
            content_hash=message_hash(fetched.text),
            user_id=fetched.user,
            text=fetched.text,
            subtype=fetched.subtype,
            edited_ts=fetched.edited_ts,
        )

    def _apply(
        self,
        source_id: str,
        fetched: FetchedMessage,
        result: SyncResult,
        committed: list[str],
        unresolved: list[str],
    ) -> bool:
        """Persist one message. Returns False when ordering is unknowable.

        A message whose ``ts`` fails validation has no position on the
        timeline, so the batch cannot know what "before it" means. That
        blocks the watermark entirely rather than guessing.
        """
        result.total += 1
        if not is_valid_ts(fetched.ts):
            result.rejected += 1
            result.errors.append(f"reject:invalid_ts:{fetched.ts!r}")
            return False

        try:
            outcome = self.store.upsert_message(self._to_message(source_id, fetched))
        except (SlackStoreError, SlackIdentityError) as exc:
            result.rejected += 1
            result.errors.append(f"{getattr(exc, 'code', 'reject:unknown')}:{fetched.ts}")
            unresolved.append(fetched.ts)
            return True
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort the run
            logger.exception("Slack upsert failed for %s", fetched.ts)
            result.failed += 1
            result.errors.append(redact(str(exc)))
            unresolved.append(fetched.ts)
            return True

        if outcome == UPSERT_INSERTED:
            result.ingested += 1
        elif outcome == UPSERT_UPDATED:
            result.updated += 1
        elif outcome == UPSERT_NOOP:
            result.noop += 1
        committed.append(fetched.ts)
        return True

    def _finish(
        self,
        source_id: str,
        result: SyncResult,
        committed: list[str],
        unresolved: list[str],
        *,
        blocked: bool,
    ) -> SyncResult:
        source = self.store.require_source(source_id)
        previous = source.last_watermark
        if blocked:
            # Unorderable input: hold the checkpoint where it is.
            result.watermark = previous
        else:
            result.watermark = safe_watermark(committed, unresolved, previous)

        if result.watermark != previous:
            processed = source.documents_processed + result.ingested
            self.store.save_checkpoint(source_id, result.watermark, processed)
        if result.errors:
            self.store.record_error(source_id, "; ".join(result.errors[:10]))
        if source.status != SOURCE_QUARANTINED:
            self.store.set_status(source_id, SOURCE_ACTIVE)
        return result

    # ── Public operations ─────────────────────────────────────────────

    def sync(self, source_id: str, *, limit: int = 200) -> SyncResult:
        """Incremental collection from the checkpoint forward."""
        result = SyncResult(source_id=source_id)
        denial = self._check_state(source_id)
        if denial:
            result.quarantined += 1
            result.errors.append(denial)
            result.watermark = self.store.require_source(source_id).last_watermark
            return result

        _info, may_fetch = self._run_gate(source_id, result)
        if not may_fetch:
            return result

        source = self.store.require_source(source_id)
        committed: list[str] = []
        unresolved: list[str] = []
        blocked = False
        try:
            for fetched in self.connector.history(
                source.channel_id, oldest=source.last_watermark, limit=limit
            ):
                if not self._apply(source_id, fetched, result, committed, unresolved):
                    blocked = True
        except Exception as exc:  # noqa: BLE001 - remote enumeration failure
            logger.warning("Slack history enumeration failed: %s", redact(str(exc)))
            result.failed += 1
            result.errors.append(redact(str(exc)))
            blocked = True

        return self._finish(
            source_id, result, committed, unresolved, blocked=blocked
        )

    def reconcile(
        self, source_id: str, *, since: str, until: str = ""
    ) -> SyncResult:
        """Diff a bounded window against local state. Only tombstone path.

        ``since`` is mandatory (R23) so a whole-channel reconcile has to
        be asked for explicitly.
        """
        if not is_valid_ts(since):
            raise SlackStoreError(
                "reject:invalid_ts", f"--since must be a Slack ts, got {since!r}"
            )
        if until and not is_valid_ts(until):
            raise SlackStoreError(
                "reject:invalid_ts", f"--until must be a Slack ts, got {until!r}"
            )

        result = SyncResult(source_id=source_id)
        denial = self._check_state(source_id)
        if denial:
            result.quarantined += 1
            result.errors.append(denial)
            result.watermark = self.store.require_source(source_id).last_watermark
            return result

        _info, may_fetch = self._run_gate(source_id, result)
        if not may_fetch:
            return result

        source = self.store.require_source(source_id)

        # Enumerate the whole channel, then window it locally. The
        # protocol has no `latest` parameter, and a manual reconcile of
        # one channel is cheap enough that this is not worth a wider API.
        # ponytail: full enumeration per reconcile; add a `latest` bound
        # to SlackConnector if a channel ever gets large enough to care.
        try:
            remote = list(
                self.connector.history(source.channel_id, oldest="", limit=MAX_WINDOW)
            )
        except Exception as exc:  # noqa: BLE001
            # R24: a partial response must never be read as a deletion.
            message = redact(str(exc))
            logger.warning("Slack reconcile aborted before diffing: %s", message)
            result.failed += 1
            result.errors.append(message)
            self.store.record_error(source_id, message)
            result.watermark = source.last_watermark
            return result

        # R24 again, for data that parsed but is unusable. A message whose
        # ts is malformed cannot be matched against a local key, so it
        # would look absent and its local copy would be tombstoned even
        # though the remote still has it. Absence must never be inferred
        # from a degraded response, so abort exactly like a transport
        # failure: no tombstone, no watermark movement.
        invalid = [m for m in remote if not is_valid_ts(m.ts)]
        if invalid:
            message = (
                f"{RECONCILE_MALFORMED_REMOTE}: {len(invalid)} remote message(s) "
                f"have an unusable ts; refusing to infer deletions"
            )
            logger.warning("Slack reconcile aborted before diffing: %s", message)
            # Counted as a run failure, exactly like the transport abort
            # above: the reconcile refused to run, which must not reach a
            # caller as a success. Per-item `rejected` would leave the
            # CLI exit code at 0 and a wrapper script would carry on as
            # though reconciliation had completed. The item count stays
            # in the message rather than being double-counted here.
            result.failed += 1
            result.errors.append(message)
            self.store.record_error(source_id, message)
            result.watermark = source.last_watermark
            return result

        window = [
            m for m in remote
            if m.ts >= since and (not until or m.ts <= until)
        ]

        remote_keys = {
            message_key_for_source(source_id, m.ts): m for m in window
        }
        local = self.store.list_messages(
            source_id, since=since, until=until, limit=MAX_WINDOW
        )

        committed: list[str] = []
        unresolved: list[str] = []

        for local_msg in local:
            if local_msg.message_key not in remote_keys:
                outcome = self.store.tombstone_message(
                    local_msg.message_key, RECONCILE_REMOTE_ABSENT
                )
                result.total += 1
                if outcome == TOMBSTONED:
                    result.tombstoned += 1
                committed.append(local_msg.ts)

        for fetched in window:
            self._apply(source_id, fetched, result, committed, unresolved)

        return self._finish(
            source_id, result, committed, unresolved, blocked=False
        )

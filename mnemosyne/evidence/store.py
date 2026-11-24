"""Strictly read-only SQLite access for evidence search.

Nothing here may create, migrate, checkpoint, or otherwise write the store.
``KnowledgeGraph(...)`` is deliberately NOT used: its constructor creates the
database, runs schema migrations, and switches journal modes.

SQLite caveat handled here: opening a WAL-mode database with ``mode=ro`` still
creates the ``-wal``/``-shm`` side files when they are absent, which is a write
to the store directory, and ``PRAGMA journal_mode`` on an ``immutable`` WAL
database does the same. So the mode is chosen from the side files alone, using
ONE canonical path:

* no side files -> ``immutable=1`` (touches nothing; covers a cleanly closed WAL
  store and an idle rollback-journal store). A writer appearing during the read
  is detected by comparing file state taken before mode selection with the state
  after the read, and reported as ``store_changed_during_read``.
* live ``-wal`` and ``-shm`` -> ``mode=ro``. Nothing is created and
  database/WAL bytes are never modified. SQLite itself records WAL read marks in
  the volatile ``-shm`` index (it holds no store data and is rebuilt by SQLite);
  that cannot be avoided for a live WAL reader.
* ``-wal`` content or ``-shm`` without its partner -> ``store_recovery_required``;
  recovery is a write.
* a ``-journal`` -> ``mode=ro``; a hot journal makes SQLite refuse the read,
  reported as ``store_recovery_required``; a clean persisted journal reads fine.

No raw file descriptor is ever opened on the database file: on POSIX, closing an
unrelated descriptor drops other connections' advisory locks.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

SNAPSHOT_IMMUTABLE = "immutable"
SNAPSHOT_WAL = "wal-shared"
SNAPSHOT_ROLLBACK = "rollback-journal"

_clock = time.monotonic

REQUIRED_COLUMNS = {
    "entities": {
        "id", "type", "name", "properties", "updated_at", "version", "scope_id", "source_channel",
    },
    "scopes": {"id"},
}
LIFECYCLE_COLUMNS = {
    "lifecycle_sources": {
        "source_id", "revision", "scope_id", "source_channel", "applied_revision", "state",
        "applied_digest",
    },
    "lifecycle_legacy": {"kind", "target_id"},
}


class StoreUnavailable(Exception):
    """The store cannot be read without modifying it, or is not usable."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class SearchTimeout(Exception):
    """The operation deadline expired."""


@dataclass
class Snapshot:
    conn: sqlite3.Connection
    mode: str
    path: Path
    fingerprint: Tuple[Tuple[str, Optional[int], Optional[int]], ...]


class Deadline:
    def __init__(self, timeout_ms: int) -> None:
        self._end = _clock() + timeout_ms / 1000.0

    def expired(self) -> bool:
        return _clock() >= self._end

    def check(self) -> None:
        if self.expired():
            raise SearchTimeout()

    def remaining_ms(self) -> int:
        return max(0, int((self._end - _clock()) * 1000))


def _fingerprint(path: Path) -> Tuple[Tuple[str, Optional[int], Optional[int]], ...]:
    out: list[Tuple[str, Optional[int], Optional[int]]] = []
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            st = os.stat(str(path) + suffix)
            out.append((suffix, st.st_size, st.st_mtime_ns))
        except FileNotFoundError:
            out.append((suffix, None, None))
    return tuple(out)


def _size(path: str) -> Optional[int]:
    try:
        return os.stat(path).st_size
    except FileNotFoundError:
        return None


def open_snapshot(path: Path, deadline: Deadline) -> Snapshot:
    """Open ``path`` read-only without creating or modifying any file."""
    try:
        canonical = path.resolve()
        st = os.stat(canonical)
        if not canonical.is_file():
            raise StoreUnavailable("store_unreadable", "the knowledge store is not a file")
    except FileNotFoundError:
        raise StoreUnavailable("store_missing", "the knowledge store does not exist") from None
    except (OSError, ValueError, RuntimeError):
        raise StoreUnavailable("store_unreadable", "the knowledge store is not accessible") from None
    if st.st_size == 0:
        raise StoreUnavailable(
            "store_uninitialized", "the knowledge store is not an initialized database"
        )

    fingerprint = _fingerprint(canonical)  # taken before any mode decision
    uri_base = canonical.as_uri()
    base = str(canonical)
    wal, shm, journal = (_size(base + suffix) for suffix in ("-wal", "-shm", "-journal"))
    if journal:
        # SQLite decides: a clean (e.g. PERSIST, zeroed) journal reads normally,
        # a hot one makes the read-only open fail with a recovery error.
        mode, uri = SNAPSHOT_ROLLBACK, uri_base + "?mode=ro"
    elif wal is not None and shm is not None:
        mode, uri = SNAPSHOT_WAL, uri_base + "?mode=ro"
    elif wal or shm is not None:
        raise StoreUnavailable(
            "store_recovery_required", "WAL content exists without a matching shared-memory index"
        )
    else:
        # No side files: nothing is mid-flight. Read the main file untouched.
        mode, uri = SNAPSHOT_IMMUTABLE, uri_base + "?immutable=1"

    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(
            uri, uri=True, timeout=max(0.05, deadline.remaining_ms() / 1000.0), isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        _install_deadline(conn, deadline)
        conn.execute("BEGIN")
    except sqlite3.Error as exc:
        if conn is not None:
            conn.close()
        raise translate_error(exc) from None
    return Snapshot(conn=conn, mode=mode, path=canonical, fingerprint=fingerprint)


def close_snapshot(snapshot: Snapshot) -> None:
    try:
        if snapshot.conn.in_transaction:
            snapshot.conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass
    finally:
        snapshot.conn.close()


def verify_unchanged(snapshot: Snapshot) -> None:
    """The mode chosen at open time must still describe the store after the read."""
    now = _fingerprint(snapshot.path)
    if snapshot.mode == SNAPSHOT_IMMUTABLE:
        changed = now != snapshot.fingerprint
    elif snapshot.mode == SNAPSHOT_WAL:
        changed = now[1][1] is None or now[2][1] is None  # -wal/-shm disappeared
    else:
        changed = False
    if changed:
        raise StoreUnavailable(
            "store_changed_during_read", "the store changed while it was being read"
        )


def _install_deadline(conn: sqlite3.Connection, deadline: Deadline) -> None:
    def handler() -> int:
        return 1 if deadline.expired() else 0

    conn.set_progress_handler(handler, 2000)


def translate_error(exc: sqlite3.Error) -> Exception:
    text = str(exc).lower()
    if "interrupted" in text:
        return SearchTimeout()
    if "locked" in text or "busy" in text:
        return StoreUnavailable("store_busy", "the knowledge store is busy")
    if "readonly" in text or "read-only" in text:
        return StoreUnavailable(
            "store_recovery_required", "the store needs writer recovery before it can be read"
        )
    if "unable to open" in text:
        return StoreUnavailable("store_unreadable", "the knowledge store cannot be opened read-only")
    return StoreUnavailable("store_unreadable", "the knowledge store is not a readable database")


def check_schema(conn: sqlite3.Connection) -> bool:
    """Verify required tables/columns exist; returns whether lifecycle tables exist."""
    try:
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table, columns in REQUIRED_COLUMNS.items():
            if table not in tables:
                raise StoreUnavailable("store_uninitialized", f"the store has no {table} table")
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if not columns <= have:
                raise StoreUnavailable(
                    "store_schema_unsupported", f"the {table} table lacks required columns"
                )
        lifecycle = set(LIFECYCLE_COLUMNS) & tables
        if not lifecycle:
            return False
        if lifecycle != set(LIFECYCLE_COLUMNS):
            raise StoreUnavailable("store_schema_unsupported", "incomplete lifecycle tables")
        for table, columns in LIFECYCLE_COLUMNS.items():
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if not columns <= have:
                raise StoreUnavailable(
                    "store_schema_unsupported", f"the {table} table lacks required columns"
                )
        return True
    except sqlite3.Error as exc:
        raise translate_error(exc) from None

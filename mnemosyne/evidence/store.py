"""Strictly read-only SQLite access for evidence search.

Nothing here may create, migrate, checkpoint, or otherwise write the store.
``KnowledgeGraph(...)`` is deliberately NOT used: its constructor creates the
database, runs schema migrations, and switches journal modes.

SQLite caveat handled here: opening a WAL-mode database with ``mode=ro`` still
creates the ``-wal``/``-shm`` side files when they are absent, which is a write
to the store directory. So:

* WAL database, no side files, no pending journal -> ``immutable=1`` (touches
  nothing). A writer starting mid-read is detected by comparing file state
  before/after and reported as ``store_changed_during_read``.
* WAL database with live ``-wal`` and ``-shm`` -> ``mode=ro``; both side files
  already exist, so nothing is created, and WAL snapshot isolation applies.
* Anything that would need recovery (``-wal`` content without ``-shm``, a
  ``-journal``) -> ``store_recovery_required``; recovery is a write.
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

_SQLITE_MAGIC = b"SQLite format 3\x00"

LIFECYCLE_COLUMNS = {
    "lifecycle_state": {"generation"},
    "lifecycle_sources": {"source_id", "revision", "scope_id"},
}

REQUIRED_COLUMNS = {
    "entities": {
        "id", "type", "name", "properties", "updated_at", "version", "scope_id", "source_channel",
    },
    "scopes": {"id"},
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
    fingerprint: Tuple[object, ...]


class Deadline:
    def __init__(self, timeout_ms: int) -> None:
        self._end = time.monotonic() + timeout_ms / 1000.0

    def expired(self) -> bool:
        return time.monotonic() >= self._end

    def check(self) -> None:
        if self.expired():
            raise SearchTimeout()

    def remaining_ms(self) -> int:
        return max(0, int((self._end - time.monotonic()) * 1000))


def _fingerprint(path: Path) -> Tuple[object, ...]:
    out: list[object] = []
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            st = os.stat(str(path) + suffix)
            out.append((suffix, st.st_size, st.st_mtime_ns))
        except FileNotFoundError:
            out.append((suffix, None, None))
    return tuple(out)


def _file_size(path: str) -> Optional[int]:
    try:
        return os.stat(path).st_size
    except FileNotFoundError:
        return None


def open_snapshot(path: Path, deadline: Deadline) -> Snapshot:
    """Open ``path`` read-only without creating or modifying any file."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise StoreUnavailable("store_missing", "the knowledge store does not exist") from None
    except OSError:
        raise StoreUnavailable("store_unreadable", "the knowledge store is not accessible") from None
    if not path.is_file():
        raise StoreUnavailable("store_unreadable", "the knowledge store is not a file")
    try:
        with open(path, "rb") as handle:
            header = handle.read(100)
    except OSError:
        raise StoreUnavailable("store_unreadable", "the knowledge store is not readable") from None
    if st.st_size == 0 or not header.startswith(_SQLITE_MAGIC) or len(header) < 100:
        raise StoreUnavailable("store_uninitialized", "the knowledge store is not an initialized database")
    is_wal = header[18] == 2 and header[19] == 2

    base = str(path)
    wal, shm, journal = _file_size(base + "-wal"), _file_size(base + "-shm"), _file_size(base + "-journal")
    if journal:
        raise StoreUnavailable(
            "store_recovery_required", "a hot rollback journal needs writer recovery"
        )
    uri_base = path.resolve().as_uri()
    if is_wal and shm is None and not wal:
        mode, uri = SNAPSHOT_IMMUTABLE, uri_base + "?immutable=1"
    elif is_wal and shm is not None and wal is not None:
        mode, uri = SNAPSHOT_WAL, uri_base + "?mode=ro"
    elif is_wal:
        raise StoreUnavailable(
            "store_recovery_required", "WAL content exists without a shared-memory index"
        )
    else:
        mode, uri = SNAPSHOT_ROLLBACK, uri_base + "?mode=ro"

    fingerprint = _fingerprint(path.resolve())
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
    return Snapshot(conn=conn, mode=mode, path=path.resolve(), fingerprint=fingerprint)


def close_snapshot(snapshot: Snapshot) -> None:
    try:
        if snapshot.conn.in_transaction:
            snapshot.conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass
    finally:
        snapshot.conn.close()


def verify_unchanged(snapshot: Snapshot) -> None:
    """Immutable reads are only valid if no writer touched the store meanwhile."""
    if snapshot.mode == SNAPSHOT_IMMUTABLE and _fingerprint(snapshot.path) != snapshot.fingerprint:
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
                raise StoreUnavailable(
                    "store_uninitialized", f"the store has no {table} table"
                )
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if not columns <= have:
                raise StoreUnavailable(
                    "store_schema_unsupported", f"the {table} table lacks required columns"
                )
        lifecycle = {"lifecycle_state", "lifecycle_sources"} & tables
        if not lifecycle:
            return False
        if len(lifecycle) != 2:
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


"""Strictly read-only SQLite access for evidence search.

Nothing here may create, migrate, checkpoint, or otherwise write the store.
``KnowledgeGraph(...)`` is deliberately NOT used: its constructor creates the
database, runs schema migrations, and switches journal modes.

SQLite caveats handled here. Opening a WAL-mode database with ``mode=ro``
creates the ``-wal``/``-shm`` side files when they are absent, and a live WAL
reader records read marks in the shared ``-shm`` file; both are writes to the
store directory. ``PRAGMA journal_mode`` cannot be used to tell the modes apart
(``immutable=1`` reports ``delete`` for WAL databases) and a raw read of the
database file on POSIX would drop other in-process connections' advisory locks
when closed. So the access mode is chosen from the side files of the canonical
(symlink-resolved) path alone:

* no side files (or only an empty ``-wal``) -> ``mode=ro&immutable=1`` (touches
  nothing; covers a cleanly closed WAL store and an idle rollback-journal
  store). A writer appearing during the read is detected by comparing file
  state taken before mode selection with the state after the read
  (``store_changed_during_read``).
* any live state (``-wal`` content, ``-shm`` or ``-journal``) -> a private
  snapshot: the main file (via an immutable SQLite connection's ``serialize``)
  and the side files' bytes are copied into a temporary directory and read
  there, so SQLite's WAL recovery, hot-journal rollback and read marks happen
  on the copy. The copy is retried if the main file or a side-file header
  changes while copying. The original is only ever opened ``immutable``, so its
  directory is never written. A copy may include a commit frame that source
  readers have not yet been shown: a complete, checksum-valid transaction that a
  recovering opener would also see, though a writer that then fails before
  syncing could still lose it. Torn frames fail their checksum and are ignored.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

SNAPSHOT_IMMUTABLE = "immutable"
SNAPSHOT_COPY = "private-copy"

MAX_COPY_BYTES = 256 * 1024 * 1024
_COPY_ATTEMPTS = 3
_HEADER_BYTES = 32
_SIDE_FILES = ("-wal", "-journal")

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

Fingerprint = Tuple[Tuple[str, Optional[int], Optional[int]], ...]


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
    fingerprint: Fingerprint
    cleanup: Optional[Callable[[], None]] = None
    bypass_reason: Optional[str] = None  # set when freshness is unprovable for this snapshot
    main_digest: Optional[str] = None  # content digest of the main file (immutable mode)


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


def _fingerprint(path: Path) -> Fingerprint:
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


def _main_key(path: Path) -> Tuple[int, int]:
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def _side_state(base: str) -> dict[str, Optional[bytes]]:
    """Existence and header bytes of each side file (cheap restart/commit detector)."""
    out: dict[str, Optional[bytes]] = {}
    for suffix in _SIDE_FILES:
        try:
            with open(base + suffix, "rb") as handle:
                out[suffix] = handle.read(_HEADER_BYTES)
        except FileNotFoundError:
            out[suffix] = None
    return out


def _read_bounded(path: str, budget: int) -> Optional[bytes]:
    try:
        size = os.stat(path).st_size
    except FileNotFoundError:
        return None
    if size > budget:
        raise StoreUnavailable(
            "store_too_large", "the live store is too large to snapshot without writing to it"
        )
    with open(path, "rb") as handle:
        return handle.read(size)


def _private_copy(
    canonical: Path, uri_base: str, deadline: Deadline
) -> Tuple[sqlite3.Connection, Callable[[], None]]:
    """Copy the main file and side files to a temp dir; return (connection, cleanup)."""
    if not hasattr(sqlite3.Connection, "serialize"):
        raise StoreUnavailable(
            "store_snapshot_unsupported", "this SQLite build cannot snapshot a live store"
        )
    base = str(canonical)
    main_bytes = b""
    side_bytes: dict[str, bytes] = {}
    for _ in range(_COPY_ATTEMPTS):
        deadline.check()
        main_before = _main_key(canonical)
        if main_before[0] > MAX_COPY_BYTES:  # checked from stat, before any allocation
            raise StoreUnavailable(
                "store_too_large", "the live store is too large to snapshot without writing to it"
            )
        sides_before = _side_state(base)
        src = sqlite3.connect(uri_base + "?mode=ro&immutable=1", uri=True)
        try:
            main_bytes = src.serialize()
        finally:
            src.close()
        budget = MAX_COPY_BYTES - len(main_bytes)
        side_bytes = {}
        for suffix in _SIDE_FILES:
            data = _read_bounded(base + suffix, budget)
            if data is not None:
                side_bytes[suffix] = data
                budget -= len(data)
        deadline.check()
        if _main_key(canonical) == main_before and _side_state(base) == sides_before:
            break
    else:
        raise StoreUnavailable("store_busy", "the store kept changing while it was snapshotted")

    tmp = tempfile.mkdtemp(prefix="mnemosyne-evidence-")

    def cleanup() -> None:
        def retry(func: Callable[..., object], target: str, _exc: object) -> None:
            # Never leave a whole-store copy behind: make it writable, empty it, then drop it.
            try:
                os.chmod(target, 0o700)
                if os.path.isfile(target):
                    os.truncate(target, 0)
                func(target)
            except OSError:
                pass

        if sys.version_info >= (3, 12):
            shutil.rmtree(tmp, onexc=retry)
        else:
            shutil.rmtree(tmp, onerror=retry)

    conn: Optional[sqlite3.Connection] = None
    try:
        snap = Path(tmp) / "snapshot.db"
        snap.write_bytes(main_bytes)
        for suffix, data in side_bytes.items():
            Path(str(snap) + suffix).write_bytes(data)
        conn = sqlite3.connect(
            str(snap), timeout=max(0.05, deadline.remaining_ms() / 1000.0), isolation_level=None
        )
    except BaseException:
        if conn is not None:
            conn.close()
        cleanup()
        raise
    return conn, cleanup


def open_snapshot(path: Path, deadline: Deadline, wal_writers: bool = False) -> Snapshot:
    """Open ``path`` read-only without creating or modifying any file in its directory."""
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
    cleanup: Optional[Callable[[], None]] = None
    conn: Optional[sqlite3.Connection] = None
    try:
        if wal or shm is not None or journal is not None:
            mode = SNAPSHOT_COPY
            conn, cleanup = _private_copy(canonical, uri_base, deadline)
        else:
            mode = SNAPSHOT_IMMUTABLE
            conn = sqlite3.connect(
                uri_base + "?mode=ro&immutable=1", uri=True, isolation_level=None,
                timeout=max(0.05, deadline.remaining_ms() / 1000.0),
            )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        _install_deadline(conn, deadline)
        conn.execute("BEGIN")
    except sqlite3.Error as exc:
        if conn is not None:
            conn.close()
        if cleanup is not None:
            cleanup()
        raise translate_error(exc) from None
    except BaseException:
        if conn is not None:
            conn.close()
        if cleanup is not None:
            cleanup()
        raise
    bypass: Optional[str] = None
    digest: Optional[str] = None
    if mode == SNAPSHOT_COPY:
        bypass = "live_store_snapshot_unpublished"
    elif not wal_writers:
        bypass = "writer_mode_unattested"
    elif st.st_nlink != 1:
        # Another hard link would give a writer its own -wal/-shm namespace, so
        # "no side files here" would say nothing about writers using that name.
        bypass = "store_identity_unverified"
    else:
        try:
            digest = _main_digest(canonical, uri_base)
        except BaseException:
            conn.close()
            raise
        if digest is None:
            bypass = "store_too_large_to_verify"
    return Snapshot(conn, mode, canonical, fingerprint, cleanup, bypass, digest)


def _main_digest(canonical: Path, uri_base: str) -> Optional[str]:
    """SHA-256 of the main file's bytes, read through SQLite; None if it cannot be verified."""
    if not hasattr(sqlite3.Connection, "serialize") or _main_key(canonical)[0] > MAX_COPY_BYTES:
        return None
    try:
        src = sqlite3.connect(uri_base + "?mode=ro&immutable=1", uri=True)
        try:
            return hashlib.sha256(src.serialize()).hexdigest()
        finally:
            src.close()
    except sqlite3.Error as exc:
        raise translate_error(exc) from None


def close_snapshot(snapshot: Snapshot) -> None:
    try:
        if snapshot.conn.in_transaction:
            snapshot.conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass
    finally:
        snapshot.conn.close()
        if snapshot.cleanup is not None:
            snapshot.cleanup()


def verify_unchanged(snapshot: Snapshot) -> None:
    """An immutable read is only valid if no writer touched the store meanwhile.

    File state (size, mtime, side files) is compared first; when a content digest
    was taken it is compared too, so a rewrite that preserved size and mtime is
    still caught.
    """
    if snapshot.mode != SNAPSHOT_IMMUTABLE:
        return
    changed = _fingerprint(snapshot.path) != snapshot.fingerprint
    if not changed and snapshot.main_digest is not None:
        # Cacheability assumed a single-link identity at open; a link added since
        # would give a writer its own -wal/-shm namespace.
        changed = os.stat(snapshot.path).st_nlink != 1
    if not changed and snapshot.main_digest is not None:
        changed = _main_digest(snapshot.path, snapshot.path.as_uri()) != snapshot.main_digest
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

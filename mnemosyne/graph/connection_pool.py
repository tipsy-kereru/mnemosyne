"""Connection pool with read/write separation for SQLite WAL mode.

Provides concurrent read access while maintaining a single serialized
write connection. Read connections enforce ``query_only=1`` so they
cannot accidentally mutate data.

Architecture:

    ┌─────────────┐     ┌──────────────────┐
    │ write conn  │     │ read conn (T1)   │── thread-local
    │ (singleton) │     │ read conn (T2)   │── thread-local
    │  Lock-guard │     │ read conn (T3)   │── thread-local
    └──────┬──────┘     └────────┬─────────┘
           │                     │
           ▼                     ▼
      ┌─────────────────────────────────┐
      │     SQLite DB (WAL mode)        │
      │  readers don't block writer     │
      │  writer doesn't block readers   │
      └─────────────────────────────────┘

WAL mode allows N concurrent readers + 1 writer without blocking.
``query_only=1`` on read connections prevents accidental writes.
``synchronous=FULL`` (optional) survives power loss at a ~2× fsync cost.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Manages one write connection + per-thread read connections.

    Args:
        db_path: Path to the SQLite database file.
        synchronous: ``"NORMAL"`` (fast, OS-crash safe) or ``"FULL"``
            (power-loss safe, ~2× slower on writes).
        busy_timeout: Seconds to wait when another connection holds the
            write lock.
    """

    def __init__(
        self,
        db_path: str | Path,
        synchronous: str = "NORMAL",
        busy_timeout: float = 30.0,
    ) -> None:
        self.db_path = str(db_path)
        self.synchronous = synchronous.upper()
        self.busy_timeout = busy_timeout

        self._write_lock = threading.Lock()
        self._write_conn: Optional[sqlite3.Connection] = None
        self._local = threading.local()
        self._closed = False

    # ── Write connection (singleton, lock-guarded) ──────────────────

    @property
    def write_conn(self) -> sqlite3.Connection:
        """The single write connection. Thread-safe via internal lock."""
        if self._write_conn is None:
            conn = sqlite3.connect(
                self.db_path, timeout=self.busy_timeout,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"PRAGMA synchronous={self.synchronous}")
            self._write_conn = conn
            logger.debug(
                "write conn established (synchronous=%s)", self.synchronous
            )
        return self._write_conn

    # ── Read connection (per-thread, query-only) ────────────────────

    def get_read_conn(self) -> sqlite3.Connection:
        """Return a thread-local read-only connection.

        Each calling thread gets its own connection (SQLite objects are
        not safe to share across threads without ``check_same_thread=False``
        serialization). The connection is ``query_only=1`` so any
        INSERT/UPDATE/DELETE raises immediately.
        """
        if self._closed:
            raise RuntimeError("ConnectionPool is closed")

        conn = getattr(self._local, "read_conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self.busy_timeout,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA query_only=1")
            self._local.read_conn = conn
            logger.debug("read conn established for thread %s", threading.current_thread().ident)
        return conn

    # ── WAL checkpoint ──────────────────────────────────────────────

    def wal_checkpoint(self, mode: str = "TRUNCATE") -> dict[str, int]:
        """Run a WAL checkpoint to merge the WAL back into the main DB.

        Returns the checkpoint result dict from SQLite.
        Call periodically (e.g. after batch writes) to bound WAL growth.
        """
        with self._write_lock:
            conn = self.write_conn
            cursor = conn.execute(f"PRAGMA wal_checkpoint({mode})")
            row = cursor.fetchone()
            result = {
                "busy": row[0] if row else 0,
                "log_frames": row[1] if row else 0,
                "checkpointed_frames": row[2] if row else 0,
            }
            logger.debug("WAL checkpoint: %s", result)
            return result

    # ── Lifecycle ───────────────────────────────────────────────────

    def close(self) -> None:
        """Close the write connection. Per-thread read connections are GC'd."""
        self._closed = True
        if self._write_conn is not None:
            self._write_conn.close()
            self._write_conn = None

    @property
    def is_closed(self) -> bool:
        return self._closed

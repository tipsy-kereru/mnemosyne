"""Tests for ConnectionPool read/write separation (Phase 0 contract gate).

Verifies:
- Read connections are query_only (writes raise)
- Write connection works normally
- Per-thread read connections are distinct
- WAL checkpoint executes
- KnowledgeGraph integration (get_read_conn, wal_checkpoint)
- synchronous=FULL option
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from mnemosyne.graph.connection_pool import ConnectionPool
from mnemosyne.graph.knowledge_graph import KnowledgeGraph


@pytest.fixture
def pool(tmp_path: Path) -> ConnectionPool:
    """Fresh pool on a temp DB with a seed table."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO test VALUES (1, 'hello')")
    conn.commit()
    conn.close()
    return ConnectionPool(db)


class TestReadConnection:
    def test_read_conn_returns_data(self, pool):
        conn = pool.get_read_conn()
        row = conn.execute("SELECT * FROM test WHERE id = 1").fetchone()
        assert row["val"] == "hello"

    def test_read_conn_blocks_writes(self, pool):
        """query_only=1 prevents accidental writes on read connections."""
        conn = pool.get_read_conn()
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO test VALUES (2, 'nope')")

    def test_read_conn_is_thread_local(self, pool):
        """Each thread gets its own read connection."""
        main_conn = pool.get_read_conn()
        other_conn_ref = []

        def get_in_thread():
            other_conn_ref.append(pool.get_read_conn())

        t = threading.Thread(target=get_in_thread)
        t.start()
        t.join()

        assert other_conn_ref[0] is not main_conn

    def test_read_conn_reused_within_same_thread(self, pool):
        """Same thread gets the same connection on repeated calls."""
        a = pool.get_read_conn()
        b = pool.get_read_conn()
        assert a is b


class TestWriteConnection:
    def test_write_conn_works(self, pool):
        conn = pool.write_conn
        conn.execute("INSERT INTO test VALUES (2, 'written')")
        conn.commit()
        row = conn.execute("SELECT * FROM test WHERE id = 2").fetchone()
        assert row["val"] == "written"

    def test_write_conn_is_singleton(self, pool):
        assert pool.write_conn is pool.write_conn


class TestWALCheckpoint:
    def test_checkpoint_returns_result(self, pool):
        conn = pool.write_conn
        conn.execute("INSERT INTO test VALUES (3, 'data')")
        conn.commit()
        result = pool.wal_checkpoint()
        assert "busy" in result
        assert "checkpointed_frames" in result


class TestSynchronousOption:
    def test_full_mode(self, tmp_path):
        db = tmp_path / "full.db"
        sqlite3.connect(str(db)).close()  # create file
        pool = ConnectionPool(db, synchronous="FULL")
        conn = pool.write_conn
        pragma = conn.execute("PRAGMA synchronous").fetchone()
        assert pragma[0] == 2  # FULL = 2
        pool.close()

    def test_normal_mode(self, pool):
        conn = pool.write_conn
        pragma = conn.execute("PRAGMA synchronous").fetchone()
        assert pragma[0] == 1  # NORMAL = 1


class TestKnowledgeGraphIntegration:
    def test_kg_has_get_read_conn(self, tmp_path):
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.db"))
        read_conn = kg.get_read_conn()
        assert read_conn is not None
        # Read conn should be query_only
        with pytest.raises(sqlite3.OperationalError):
            read_conn.execute("INSERT INTO entities VALUES ('x')")
        kg.close()

    def test_kg_has_wal_checkpoint(self, tmp_path):
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.db"))
        result = kg.wal_checkpoint()
        assert "busy" in result
        kg.close()

    def test_kg_synchronous_param(self, tmp_path):
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.db"), synchronous="FULL")
        pragma = kg.conn.execute("PRAGMA synchronous").fetchone()
        assert pragma[0] == 2
        kg.close()

    def test_kg_close_closes_pool(self, tmp_path):
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.db"))
        kg.close()
        assert kg._pool.is_closed

    def test_concurrent_reads_during_write(self, tmp_path):
        """WAL mode: readers don't block writer, writer doesn't block readers."""
        kg = KnowledgeGraph(db_path=str(tmp_path / "concurrent.db"))

        # Seed an entity
        from mnemosyne.graph.knowledge_graph import Entity
        kg.add_entity(Entity(
            id="e1", type="test", name="test",
            properties={}, created_at="2026-01-01", updated_at="2026-01-01",
        ))

        errors = []

        def reader():
            try:
                conn = kg.get_read_conn()
                for _ in range(20):
                    conn.execute("SELECT COUNT(*) FROM entities").fetchone()
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(10):
                    kg.add_entity(Entity(
                        id=f"e{i+10}", type="test", name=f"t{i}",
                        properties={}, created_at="2026-01-01", updated_at="2026-01-01",
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(3)]
        threads.append(threading.Thread(target=writer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent errors: {errors}"
        count = kg.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        assert count == 11  # 1 seed + 10 written
        kg.close()

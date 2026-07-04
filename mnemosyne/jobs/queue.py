"""
Job queue for durable background task processing.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Job status enumeration."""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    """Job representation."""
    job_id: str
    job_type: str
    payload: Dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    parent_job_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary."""
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "payload": self.payload,
            "status": self.status.value if isinstance(self.status, JobStatus) else self.status,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
            "parent_job_id": self.parent_job_id,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Create job from dictionary."""
        status = data.get("status", "pending")
        if isinstance(status, str):
            status = JobStatus(status)

        return cls(
            job_id=data["job_id"],
            job_type=data["job_type"],
            payload=data.get("payload", {}),
            status=status,
            attempts=data.get("attempts", 0),
            max_attempts=data.get("max_attempts", 3),
            created_at=data.get("created_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message"),
            parent_job_id=data.get("parent_job_id"),
            result=data.get("result", {}),
        )


class JobQueue:
    """Durable job queue for background tasks."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize job queue.

        Args:
            db_path: Path to SQLite database.
                Uses default if None.
        """
        if db_path is None:
            db_path = Path.home() / "mnemosyne" / "graph" / "knowledge.db"

        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(
            str(self.db_path), timeout=30.0, check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row

        self._init_schema()

    def _init_schema(self):
        """Initialize job queue schema."""
        cursor = self.conn.cursor()

        # Jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_queue (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                error_message TEXT,
                parent_job_id TEXT,
                result TEXT,
                FOREIGN KEY (parent_job_id) REFERENCES job_queue(job_id)
            )
        """)

        # Indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_queue_status
            ON job_queue(status, created_at)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_queue_parent
            ON job_queue(parent_job_id)
        """)

        self.conn.commit()

    def submit(
        self,
        job_type: str,
        payload: Dict[str, Any],
        parent_id: Optional[str] = None,
        max_attempts: int = 3,
    ) -> str:
        """Submit a job to the queue.

        Args:
            job_type: Type of job (e.g., 'extract_facts').
            payload: Job data (will be JSON serialized).
            parent_id: Optional parent job ID.
            max_attempts: Maximum retry attempts.

        Returns:
            Job ID.
        """
        import uuid

        job_id = f"job_{uuid.uuid4().hex}"

        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO job_queue
            (job_id, job_type, payload, parent_job_id, max_attempts)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, job_type, json.dumps(payload), parent_id, max_attempts),
        )
        self.conn.commit()

        logger.info(f"Submitted job {job_id} of type {job_type}")
        return job_id

    def acquire(self, limit: int = 10) -> List[Job]:
        """Acquire pending jobs for processing.

        Args:
            limit: Maximum number of jobs to acquire.

        Returns:
            List of acquired jobs.
        """
        cursor = self.conn.cursor()

        # Get pending jobs that aren't already running
        # Using UPDATE with RETURNING for atomicity
        cursor.execute(
            """
            UPDATE job_queue
            SET status = 'running',
                started_at = ?
            WHERE rowid IN (
                SELECT rowid FROM job_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
            )
            RETURNING *
            """,
            (datetime.now().isoformat(), limit),
        )

        self.conn.commit()

        jobs = []
        for row in cursor.fetchall():
            job_data = dict(row)
            job_data["payload"] = json.loads(job_data["payload"])
            job_data["result"] = json.loads(job_data["result"]) if job_data.get("result") else {}
            jobs.append(Job.from_dict(job_data))

        if jobs:
            logger.debug(f"Acquired {len(jobs)} jobs for processing")

        return jobs

    def complete(self, job_id: str, result: Optional[Dict] = None) -> None:
        """Mark job as done with result.

        Args:
            job_id: Job to complete.
            result: Optional result data.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE job_queue
            SET status = 'done',
                completed_at = ?,
                result = ?
            WHERE job_id = ?
            """,
            (datetime.now().isoformat(), json.dumps(result or {}), job_id),
        )
        self.conn.commit()

        logger.info(f"Completed job {job_id}")

    def fail(self, job_id: str, error: str, retry: bool = True) -> None:
        """Mark job as failed.

        Args:
            job_id: Job that failed.
            error: Error message.
            retry: Whether to retry (if attempts < max_attempts).
        """
        cursor = self.conn.cursor()

        # Check attempts
        row = cursor.execute(
            "SELECT attempts, max_attempts FROM job_queue WHERE job_id = ?",
            (job_id,),
        ).fetchone()

        if not row:
            logger.warning(f"Job {job_id} not found")
            return

        attempts = row["attempts"]
        max_attempts = row["max_attempts"]

        if retry and attempts < max_attempts:
            # Increment attempts and reset to pending
            cursor.execute(
                """
                UPDATE job_queue
                SET status = 'pending',
                    attempts = attempts + 1,
                    error_message = ?,
                    started_at = NULL
                WHERE job_id = ?
                """,
                (error, job_id),
            )
            logger.info(f"Failed job {job_id}, will retry (attempt {attempts + 1}/{max_attempts})")
        else:
            # Mark as permanently failed
            cursor.execute(
                """
                UPDATE job_queue
                SET status = 'failed',
                    completed_at = ?,
                    error_message = ?
                WHERE job_id = ?
                """,
                (datetime.now().isoformat(), error, job_id),
            )
            logger.warning(f"Job {job_id} permanently failed: {error}")

        self.conn.commit()

    def get_status(self, job_id: str) -> Optional[JobStatus]:
        """Get current job status.

        Args:
            job_id: Job to query.

        Returns:
            Job status or None if not found.
        """
        cursor = self.conn.cursor()
        row = cursor.execute(
            "SELECT status FROM job_queue WHERE job_id = ?", (job_id,)
        ).fetchone()

        if not row:
            return None

        return JobStatus(row["status"])

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get full job details.

        Args:
            job_id: Job to query.

        Returns:
            Job or None if not found.
        """
        cursor = self.conn.cursor()
        row = cursor.execute(
            "SELECT * FROM job_queue WHERE job_id = ?", (job_id,)
        ).fetchone()

        if not row:
            return None

        job_data = dict(row)
        job_data["payload"] = json.loads(job_data["payload"])
        job_data["result"] = json.loads(job_data["result"]) if job_data.get("result") else {}
        return Job.from_dict(job_data)

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        parent_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Job]:
        """List jobs with optional filters.

        Args:
            status: Filter by status.
            parent_id: Filter by parent job.
            limit: Maximum results.

        Returns:
            List of jobs.
        """
        cursor = self.conn.cursor()

        conditions = []
        params = []

        if status:
            conditions.append("status = ?")
            params.append(status.value)

        if parent_id:
            conditions.append("parent_job_id = ?")
            params.append(parent_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        cursor.execute(
            f"""
            SELECT * FROM job_queue
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        )

        jobs = []
        for row in cursor.fetchall():
            job_data = dict(row)
            job_data["payload"] = json.loads(job_data["payload"])
            job_data["result"] = json.loads(job_data["result"]) if job_data.get("result") else {}
            jobs.append(Job.from_dict(job_data))

        return jobs

    def purge_completed(self, older_than_days: int = 7) -> int:
        """Purge old completed jobs.

        Args:
            older_than_days: Delete jobs completed more than this many days ago.

        Returns:
            Number of jobs purged.
        """
        cursor = self.conn.cursor()

        cutoff = datetime.now().timestamp() - (older_than_days * 86400)

        cursor.execute(
            """
            DELETE FROM job_queue
            WHERE status IN ('done', 'failed')
            AND completed_at IS NOT NULL
            AND strftime('%s', completed_at) < ?
            """,
            (cutoff,),
        )

        deleted = cursor.rowcount
        self.conn.commit()

        logger.info(f"Purged {deleted} old completed jobs")
        return deleted

    def get_stats(self) -> Dict[str, int]:
        """Get queue statistics.

        Returns:
            Statistics dictionary.
        """
        cursor = self.conn.cursor()

        stats = {}

        for status in JobStatus:
            row = cursor.execute(
                "SELECT COUNT(*) as count FROM job_queue WHERE status = ?",
                (status.value,),
            ).fetchone()
            stats[status.value] = row["count"]

        return stats

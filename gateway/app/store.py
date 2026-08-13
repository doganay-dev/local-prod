from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Job:
    id: str
    state: str
    request_json: str
    prompt_id: str | None
    output_path: str | None
    width: int | None
    height: int | None
    seed: int
    error: str | None
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class Circuit:
    is_open: bool
    reason: str | None
    updated_at: float


class Store:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL CHECK (state IN ('queued','running','succeeded','failed')),
                    request_json TEXT NOT NULL,
                    prompt_id TEXT,
                    output_path TEXT,
                    width INTEGER,
                    height INTEGER,
                    seed INTEGER NOT NULL,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
                CREATE TABLE IF NOT EXISTS circuit (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    is_open INTEGER NOT NULL,
                    reason TEXT,
                    updated_at REAL NOT NULL
                );
                INSERT OR IGNORE INTO circuit(singleton, is_open, reason, updated_at)
                VALUES (1, 0, NULL, 0);
                """
            )

    @staticmethod
    def _job(row: sqlite3.Row | None) -> Job | None:
        return Job(**dict(row)) if row else None

    def get_job(self, job_id: str) -> Job | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._job(row)

    def create_job(self, job_id: str, request_json: str, seed: int) -> Job:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO jobs
                    (id, state, request_json, seed, created_at, updated_at)
                VALUES (?, 'queued', ?, ?, ?, ?)
                """,
                (job_id, request_json, seed, now, now),
            )
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            assert row is not None
            return self._job(row)  # type: ignore[return-value]

    def mark_running(self, job_id: str, prompt_id: str | None = None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET state = 'running', prompt_id = COALESCE(?, prompt_id), updated_at = ?
                WHERE id = ?
                """,
                (prompt_id, time.time(), job_id),
            )

    def set_prompt_id(self, job_id: str, prompt_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET prompt_id = ?, updated_at = ? WHERE id = ?",
                (prompt_id, time.time(), job_id),
            )

    def mark_succeeded(self, job_id: str, output_path: Path, width: int, height: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET state = 'succeeded', output_path = ?, width = ?, height = ?,
                    error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (str(output_path), width, height, time.time(), job_id),
            )

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET state = 'failed', error = ?, updated_at = ? WHERE id = ?
                """,
                (error[:4000], time.time(), job_id),
            )

    def circuit(self) -> Circuit:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM circuit WHERE singleton = 1").fetchone()
            assert row is not None
            return Circuit(bool(row["is_open"]), row["reason"], row["updated_at"])

    def open_circuit(self, reason: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE circuit SET is_open = 1, reason = ?, updated_at = ? WHERE singleton = 1
                """,
                (reason[:4000], time.time()),
            )

    def reset_circuit(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE circuit SET is_open = 0, reason = NULL, updated_at = ? WHERE singleton = 1
                """,
                (time.time(),),
            )

    def reset_failed_job(self, job_id: str) -> bool:
        """Explicitly requeue a failed job; never used by the normal edit path."""
        with self._lock, self._connect() as connection:
            result = connection.execute(
                """
                UPDATE jobs
                SET state = 'queued', prompt_id = NULL, output_path = NULL, width = NULL,
                    height = NULL, error = NULL, updated_at = ?
                WHERE id = ? AND state = 'failed'
                """,
                (time.time(), job_id),
            )
            return result.rowcount == 1

    def job_counts(self) -> dict[str, int]:
        counts = {state: 0 for state in ("queued", "running", "succeeded", "failed")}
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT state, COUNT(*) AS amount FROM jobs GROUP BY state"
            ).fetchall()
        for row in rows:
            counts[row["state"]] = row["amount"]
        return counts

    def expired_outputs(self, cutoff: float) -> list[Job]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM jobs
                WHERE state = 'succeeded' AND output_path IS NOT NULL AND updated_at < ?
                """,
                (cutoff,),
            ).fetchall()
        return [self._job(row) for row in rows]  # type: ignore[misc]

    def expire_output(self, job_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET output_path = NULL WHERE id = ? AND state = 'succeeded'",
                (job_id,),
            )

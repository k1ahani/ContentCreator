"""Job and job-log persistence."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core.ids import new_id
from app.db.connection import dumps, loads, utcnow
from app.db.repositories.base import BaseRepository
from app.domain.enums import JobStatus, JobType
from app.domain.job import Job, JobCreate, JobLogLine


class JobRepository(BaseRepository):
    def create(self, data: JobCreate) -> Job:
        job_id = new_id()
        self.db.execute(
            """
            INSERT INTO jobs
                (id, project_id, type, status, progress, stage, provider, model,
                 input, output, created_at)
            VALUES (?, ?, ?, 'queued', NULL, '', ?, ?, ?, '{}', ?)
            """,
            (
                job_id,
                data.project_id,
                data.type.value,
                data.provider,
                data.model,
                dumps(data.input),
                utcnow(),
            ),
        )
        created = self.get(job_id)
        assert created is not None
        return created

    def get(self, job_id: str) -> Job | None:
        row = self.db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return self._map(row) if row else None

    def list(
        self,
        *,
        project_id: str | None = None,
        status: JobStatus | None = None,
        type: JobType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Job]:
        clauses: list[str] = []
        params: list[object] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("status = ?")
            params.append(status.value)
        if type:
            clauses.append("type = ?")
            params.append(type.value)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        rows = self.db.query_all(
            f"SELECT * FROM jobs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            tuple(params),
        )
        return [self._map(row) for row in rows]

    def list_active(self) -> list[Job]:
        rows = self.db.query_all(
            "SELECT * FROM jobs WHERE status IN ('queued', 'running') ORDER BY created_at"
        )
        return [self._map(row) for row in rows]

    # -- state transitions -------------------------------------------------

    def mark_running(self, job_id: str) -> None:
        self.db.execute(
            "UPDATE jobs SET status = 'running', started_at = ?, progress = 0.0"
            " WHERE id = ? AND status = 'queued'",
            (utcnow(), job_id),
        )

    def update_progress(
        self, job_id: str, progress: float | None, stage: str | None = None
    ) -> None:
        if stage is None:
            self.db.execute(
                "UPDATE jobs SET progress = ? WHERE id = ?", (progress, job_id)
            )
        else:
            self.db.execute(
                "UPDATE jobs SET progress = ?, stage = ? WHERE id = ?",
                (progress, stage, job_id),
            )

    def set_model(self, job_id: str, provider: str | None, model: str | None) -> None:
        self.db.execute(
            "UPDATE jobs SET provider = ?, model = ? WHERE id = ?",
            (provider, model, job_id),
        )

    def mark_completed(self, job_id: str, output: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE jobs SET status = 'completed', progress = 1.0, output = ?,"
            " finished_at = ?, error = NULL, error_code = NULL WHERE id = ?",
            (dumps(output), utcnow(), job_id),
        )

    def mark_failed(self, job_id: str, error: str, error_code: str | None = None) -> None:
        self.db.execute(
            "UPDATE jobs SET status = 'failed', error = ?, error_code = ?,"
            " finished_at = ? WHERE id = ?",
            (error, error_code, utcnow(), job_id),
        )

    def mark_cancelled(self, job_id: str) -> None:
        self.db.execute(
            "UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE id = ?",
            (utcnow(), job_id),
        )

    def requeue_orphans(self) -> int:
        """Fail jobs left ``running`` by a crash or a hard shutdown.

        Called once at startup: a job marked running with no worker behind it
        would otherwise sit in the UI forever.
        """
        cursor = self.db.execute(
            "UPDATE jobs SET status = 'failed', error = ?, error_code = 'interrupted',"
            " finished_at = ? WHERE status IN ('queued', 'running')",
            ("اجرای این وظیفه به دلیل بسته‌شدن برنامه ناتمام ماند.", utcnow()),
        )
        return cursor.rowcount

    def delete(self, job_id: str) -> bool:
        cursor = self.db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cursor.rowcount > 0

    # -- logs --------------------------------------------------------------

    def append_log(self, job_id: str, line: JobLogLine) -> None:
        self.db.execute(
            "INSERT INTO job_logs (job_id, ts, stream, text) VALUES (?, ?, ?, ?)",
            (job_id, line.ts, line.stream, line.text),
        )

    def append_logs(self, job_id: str, lines: list[JobLogLine]) -> None:
        if not lines:
            return
        self.db.connection.executemany(
            "INSERT INTO job_logs (job_id, ts, stream, text) VALUES (?, ?, ?, ?)",
            [(job_id, line.ts, line.stream, line.text) for line in lines],
        )

    def get_logs(self, job_id: str, *, limit: int = 5000) -> list[JobLogLine]:
        rows = self.db.query_all(
            "SELECT ts, stream, text FROM job_logs WHERE job_id = ? ORDER BY id LIMIT ?",
            (job_id, limit),
        )
        return [
            JobLogLine(ts=row["ts"], stream=row["stream"], text=row["text"])
            for row in rows
        ]

    def trim_logs(self, keep_jobs: int = 200) -> int:
        """Delete logs for all but the most recent ``keep_jobs`` jobs."""
        cursor = self.db.execute(
            """
            DELETE FROM job_logs WHERE job_id NOT IN (
                SELECT id FROM jobs ORDER BY created_at DESC LIMIT ?
            )
            """,
            (keep_jobs,),
        )
        return cursor.rowcount

    @staticmethod
    def _map(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            project_id=row["project_id"],
            type=JobType(row["type"]),
            status=JobStatus(row["status"]),
            progress=row["progress"],
            stage=row["stage"],
            provider=row["provider"],
            model=row["model"],
            input=loads(row["input"]),
            output=loads(row["output"]),
            error=row["error"],
            error_code=row["error_code"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

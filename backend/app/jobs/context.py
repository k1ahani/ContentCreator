"""Job execution context.

The single object a handler receives. It gives the handler everything it needs
- services, the job's input, progress reporting, logging, cancellation - and
nothing it does not.

Log batching matters here. A one-hour render emits thousands of FFmpeg lines;
one ``INSERT`` per line would dominate the runtime and hammer the database.
Lines are buffered and flushed on a size or time threshold, while being
published to the event bus immediately so the live console stays responsive.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.core.paths import PATHS
from app.db.repositories.jobs import JobRepository
from app.domain.job import Job, JobEvent, JobLogLine
from app.jobs.events import EventBus
from app.process import CancelToken

if TYPE_CHECKING:  # avoids a circular import at runtime
    from app.container import ServiceContainer

logger = get_logger(__name__)

#: Buffered log lines before a forced flush.
_FLUSH_EVERY_LINES = 40
#: Seconds before a partial buffer is flushed anyway.
_FLUSH_EVERY_SECONDS = 2.0


@dataclass(slots=True)
class JobContext:
    """Everything a job handler is allowed to touch."""

    job: Job
    services: "ServiceContainer"
    jobs_repo: JobRepository
    events: EventBus
    cancel_token: CancelToken

    _buffer: list[JobLogLine] = field(default_factory=list, init=False)
    _last_flush: float = field(default_factory=time.monotonic, init=False)
    _last_progress: float = field(default=-1.0, init=False)

    # -- input -------------------------------------------------------------

    @property
    def input(self) -> dict[str, Any]:
        return self.job.input

    def require(self, key: str) -> Any:
        """Fetch a required input value, failing loudly when absent."""
        if key not in self.job.input:
            raise KeyError(f"job {self.job.id} is missing required input {key!r}")
        return self.job.input[key]

    @property
    def project_id(self) -> str:
        project_id = self.job.project_id
        if not project_id:
            raise ValueError(f"job {self.job.id} has no project")
        return project_id

    def project_dir(self, subdir: str) -> Path:
        """A project workspace sub-directory, created if needed."""
        path = PATHS.project_subdir(self.project_id, subdir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # -- cancellation ------------------------------------------------------

    @property
    def cancelled(self) -> bool:
        return self.cancel_token.cancelled

    def raise_if_cancelled(self) -> None:
        self.cancel_token.raise_if_cancelled()

    # -- progress ----------------------------------------------------------

    def set_progress(self, fraction: float | None, stage: str | None = None) -> None:
        """Report progress. ``fraction`` is 0.0-1.0, or None when unmeasurable."""
        if fraction is not None:
            fraction = max(0.0, min(1.0, fraction))
            # Suppress sub-percent churn unless the stage label changed.
            if stage is None and abs(fraction - self._last_progress) < 0.01 and fraction < 1.0:
                return
            self._last_progress = fraction

        self.jobs_repo.update_progress(self.job.id, fraction, stage)
        if stage is not None:
            self.job.stage = stage
        self.events.publish(
            JobEvent(
                kind="progress",
                job_id=self.job.id,
                progress=fraction,
                stage=stage if stage is not None else self.job.stage,
            )
        )

    def set_stage(self, stage: str) -> None:
        """Update the Persian status line without changing the percentage."""
        self.set_progress(self._last_progress if self._last_progress >= 0 else None, stage)

    def set_model(self, provider: str | None, model: str | None) -> None:
        """Record which provider/model this job actually used."""
        self.jobs_repo.set_model(self.job.id, provider, model)
        self.job.provider = provider
        self.job.model = model

    # -- logging -----------------------------------------------------------

    def log(self, stream: str, text: str) -> None:
        """Append one console line. Published live, persisted in batches."""
        if not text:
            return
        line = JobLogLine(ts=time.time(), stream=stream, text=text[:4000])
        self._buffer.append(line)

        self.events.publish(JobEvent(kind="log", job_id=self.job.id, line=line))

        if (
            len(self._buffer) >= _FLUSH_EVERY_LINES
            or time.monotonic() - self._last_flush >= _FLUSH_EVERY_SECONDS
        ):
            self.flush_logs()

    def system(self, text: str) -> None:
        self.log("system", text)

    def flush_logs(self) -> None:
        """Persist buffered log lines. Called on completion and periodically."""
        if not self._buffer:
            return
        pending, self._buffer = self._buffer, []
        self._last_flush = time.monotonic()
        try:
            self.jobs_repo.append_logs(self.job.id, pending)
        except Exception:  # logging must never fail a job
            logger.exception("could not persist %d log line(s) for job %s",
                             len(pending), self.job.id)

    # -- callback adapters -------------------------------------------------

    def progress_callback(self):
        """Adapter matching the media layer's ``(fraction, seconds)`` signature."""

        def callback(fraction: float | None, _seconds: float) -> None:
            self.set_progress(fraction)

        return callback

    def staged_progress_callback(self):
        """Adapter matching ``(fraction, stage)`` used by the ASR and TTS layers."""

        def callback(fraction: float | None, stage: str) -> None:
            self.set_progress(fraction, stage)

        return callback

    def log_callback(self):
        """Adapter matching the ``(stream, line)`` signature used everywhere."""

        def callback(stream: str, text: str) -> None:
            self.log(stream, text)

        return callback

"""Background job queue.

A fixed pool of worker threads pulling from an in-process queue. Threads rather
than processes because every long operation here releases the GIL anyway: they
are subprocess waits (FFmpeg, the Claude CLI) or native inference loops
(CTranslate2). Processes would add IPC and Windows spawn cost for nothing.

Durability is deliberately modest and honest about it: the queue lives in
memory, so jobs do not survive a restart. Anything left ``queued`` or
``running`` when the process dies is marked failed at the next startup
(:meth:`JobRepository.requeue_orphans`) rather than silently sitting in the UI
forever. For a single-user local tool that is the right trade; a persistent
queue would be real machinery for a rare case.

Cancellation is cooperative but effective: each running job owns a
:class:`~app.process.CancelToken`, and cancelling it kills the external process
tree (see ``app/process/runner.py``).
"""

from __future__ import annotations

import queue
import threading
import time
from typing import TYPE_CHECKING

from app.core.errors import AppError, JobCancelledError, ProcessCancelledError
from app.core.logging import get_logger
from app.db.repositories.jobs import JobRepository
from app.domain.enums import JobStatus
from app.domain.job import Job, JobCreate, JobEvent
from app.jobs.context import JobContext
from app.jobs.events import EventBus
from app.jobs.registry import get_handler
from app.process import CancelToken

if TYPE_CHECKING:
    from app.container import ServiceContainer

logger = get_logger(__name__)

#: Sentinel that tells a worker to exit.
_STOP = object()


class JobQueue:
    """Owns the worker pool and the lifecycle of every job."""

    def __init__(
        self,
        *,
        services: "ServiceContainer",
        events: EventBus,
        worker_count: int = 2,
    ) -> None:
        self.services = services
        self.events = events
        self.worker_count = max(1, worker_count)

        self._queue: queue.Queue = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._cancel_tokens: dict[str, CancelToken] = {}
        self._lock = threading.Lock()
        self._running = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for index in range(self.worker_count):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"job-worker-{index}",
                daemon=True,
            )
            thread.start()
            self._workers.append(thread)
        logger.info("job queue started with %d worker(s)", self.worker_count)

    def stop(self, timeout: float = 10.0) -> None:
        """Cancel running jobs and shut the pool down."""
        if not self._running:
            return
        self._running = False

        with self._lock:
            tokens = list(self._cancel_tokens.values())
        for token in tokens:
            token.cancel()

        for _ in self._workers:
            self._queue.put(_STOP)

        deadline = time.monotonic() + timeout
        for thread in self._workers:
            remaining = max(0.1, deadline - time.monotonic())
            thread.join(timeout=remaining)

        self._workers.clear()
        logger.info("job queue stopped")

    # -- submission --------------------------------------------------------

    def submit(self, data: JobCreate) -> Job:
        """Create a job row and hand it to a worker."""
        # Fail fast on an unknown type rather than at execution time.
        get_handler(data.type)

        repo = JobRepository(self.services.db)
        job = repo.create(data)
        self._queue.put(job.id)

        logger.info("queued job %s (%s)", job.id, job.type.value)
        self.events.publish(
            JobEvent(kind="status", job_id=job.id, status=JobStatus.QUEUED)
        )
        return job

    def cancel(self, job_id: str) -> bool:
        """Request cancellation. Returns False if the job is not cancellable."""
        repo = JobRepository(self.services.db)
        job = repo.get(job_id)
        if job is None or job.status.is_terminal:
            return False

        with self._lock:
            token = self._cancel_tokens.get(job_id)

        if token is not None:
            token.cancel()
            logger.info("cancellation requested for running job %s", job_id)
        else:
            # Still queued: mark it now so a worker skips it when it comes up.
            repo.mark_cancelled(job_id)
            self.events.publish(
                JobEvent(kind="status", job_id=job_id, status=JobStatus.CANCELLED)
            )
            logger.info("cancelled queued job %s", job_id)
        return True

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._cancel_tokens)

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    # -- worker ------------------------------------------------------------

    def _worker_loop(self) -> None:
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is _STOP:
                self._queue.task_done()
                break

            try:
                self._run_job(str(item))
            except Exception:  # a worker must never die
                logger.exception("unhandled error running job %s", item)
            finally:
                self._queue.task_done()

    def _run_job(self, job_id: str) -> None:
        repo = JobRepository(self.services.db)
        job = repo.get(job_id)

        if job is None:
            logger.warning("job %s disappeared before it ran", job_id)
            return
        if job.status is not JobStatus.QUEUED:
            # Cancelled while waiting, or already handled.
            logger.info("skipping job %s in status %s", job_id, job.status.value)
            return

        token = CancelToken()
        with self._lock:
            self._cancel_tokens[job_id] = token

        repo.mark_running(job_id)
        job.status = JobStatus.RUNNING
        self.events.publish(
            JobEvent(kind="status", job_id=job_id, status=JobStatus.RUNNING, progress=0.0)
        )

        context = JobContext(
            job=job,
            services=self.services,
            jobs_repo=repo,
            events=self.events,
            cancel_token=token,
        )

        started = time.monotonic()
        logger.info("running job %s (%s)", job_id, job.type.value)

        try:
            handler = get_handler(job.type)
            output = handler(context) or {}

            context.flush_logs()
            repo.mark_completed(job_id, output)
            self.events.publish(
                JobEvent(
                    kind="done",
                    job_id=job_id,
                    status=JobStatus.COMPLETED,
                    progress=1.0,
                    output=output,
                )
            )
            logger.info("job %s completed in %.1fs", job_id, time.monotonic() - started)

        except (ProcessCancelledError, JobCancelledError):
            context.system("عملیات لغو شد.")
            context.flush_logs()
            repo.mark_cancelled(job_id)
            self.events.publish(
                JobEvent(kind="done", job_id=job_id, status=JobStatus.CANCELLED)
            )
            logger.info("job %s cancelled after %.1fs", job_id, time.monotonic() - started)

        except AppError as exc:
            # A deliberate, already-translated failure.
            context.log("stderr", exc.message)
            context.flush_logs()
            message = exc.user_message
            if exc.hint:
                message = f"{message} {exc.hint}"
            repo.mark_failed(job_id, message, exc.code)
            self.events.publish(
                JobEvent(
                    kind="done",
                    job_id=job_id,
                    status=JobStatus.FAILED,
                    error=message,
                    error_code=exc.code,
                )
            )
            logger.warning("job %s failed: %s", job_id, exc.message)

        except Exception as exc:
            # Unexpected: the technical detail goes to the log file and the job
            # console, never to the user-facing message.
            logger.exception("job %s raised an unexpected error", job_id)
            context.log("stderr", f"{type(exc).__name__}: {exc}")
            context.flush_logs()
            message = "خطای پیش‌بینی‌نشده‌ای در اجرای این وظیفه رخ داد."
            repo.mark_failed(job_id, message, "internal_error")
            self.events.publish(
                JobEvent(
                    kind="done",
                    job_id=job_id,
                    status=JobStatus.FAILED,
                    error=message,
                    error_code="internal_error",
                )
            )

        finally:
            with self._lock:
                self._cancel_tokens.pop(job_id, None)

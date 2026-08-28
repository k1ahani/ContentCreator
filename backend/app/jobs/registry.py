"""Job handler registry.

Maps a :class:`~app.domain.enums.JobType` to the function that runs it.

Handlers register themselves with the :func:`register_handler` decorator;
:func:`load_handlers` imports every handler module and :func:`verify_complete`
asserts at startup that every declared job type has an implementation. Adding a
job type without a handler is therefore a startup error rather than a runtime
surprise the user discovers by clicking a button.

A handler is a plain function ``(JobContext) -> dict``. The returned dictionary
is stored as the job's output and delivered to the browser in the ``done``
event.
"""

from __future__ import annotations

from typing import Callable

from app.core.logging import get_logger
from app.domain.enums import JobType
from app.jobs.context import JobContext

logger = get_logger(__name__)

JobHandler = Callable[[JobContext], dict]

_HANDLERS: dict[JobType, JobHandler] = {}


def register_handler(job_type: JobType) -> Callable[[JobHandler], JobHandler]:
    """Decorator registering a function as the handler for ``job_type``."""

    def decorator(func: JobHandler) -> JobHandler:
        if job_type in _HANDLERS:
            raise ValueError(f"handler for {job_type.value!r} is already registered")
        _HANDLERS[job_type] = func
        logger.debug("registered job handler %s -> %s", job_type.value, func.__name__)
        return func

    return decorator


def get_handler(job_type: JobType) -> JobHandler:
    handler = _HANDLERS.get(job_type)
    if handler is None:
        raise KeyError(f"no handler registered for job type {job_type.value!r}")
    return handler


def registered_types() -> list[JobType]:
    return sorted(_HANDLERS, key=lambda t: t.value)


def verify_complete() -> None:
    """Assert every job type has a handler. Called during startup."""
    missing = [job_type.value for job_type in JobType if job_type not in _HANDLERS]
    if missing:
        raise RuntimeError(
            "these job types have no registered handler: " + ", ".join(missing)
        )
    logger.info("all %d job type(s) have handlers", len(_HANDLERS))


def load_handlers() -> None:
    """Import handler modules so their decorators run.

    Imported inside a function to avoid a circular import: handlers import
    JobContext, which lives beside this module.
    """
    from app.jobs.handlers import (  # noqa: F401, PLC0415
        audio_extract,
        subtitle_generate,
        subtitle_render,
        text_task,
        transcribe,
        tts_synthesize,
    )

    verify_complete()

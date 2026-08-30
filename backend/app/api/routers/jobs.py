"""Job endpoints: starting work, watching it, and cancelling it.

Every long operation is exposed the same way - POST returns ``202 Accepted``
with a job, and the client follows progress over SSE at ``/api/events``. No
endpoint here blocks on media processing or an AI call.
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import Container, get_container
from app.api.schemas.requests import (
    ExtractAudioRequest,
    GenerateSubtitleRequest,
    RenderSubtitleRequest,
    SyncSubtitleRequest,
    SynthesizeSpeechRequest,
    TextTaskRequest,
    TranscribeRequest,
)
from app.api.schemas.responses import JobAcceptedResponse, ListResponse, OperationResponse
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.domain.enums import JobStatus, JobType
from app.domain.job import Job, JobCreate, JobLogLine

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["jobs"])


# --------------------------------------------------------------------------
# Starting work
# --------------------------------------------------------------------------


def _accept(container: Container, data: JobCreate) -> JobAcceptedResponse:
    return JobAcceptedResponse(job=container.jobs.submit(data))


@router.post(
    "/projects/{project_id}/audio/extract",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Feature 1: extract speech-optimised audio from a video",
)
def extract_audio(
    project_id: str, body: ExtractAudioRequest, container: Container
) -> JobAcceptedResponse:
    return _accept(
        container,
        JobCreate(
            type=JobType.AUDIO_EXTRACT,
            project_id=project_id,
            input=body.model_dump(exclude_none=True),
        ),
    )


@router.post(
    "/projects/{project_id}/transcribe",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Feature 2: speech recognition, then optional LLM refinement",
)
def transcribe(
    project_id: str, body: TranscribeRequest, container: Container
) -> JobAcceptedResponse:
    return _accept(
        container,
        JobCreate(
            type=JobType.TRANSCRIBE,
            project_id=project_id,
            input=body.model_dump(exclude_none=True),
            model=body.ai_model,
        ),
    )


@router.post(
    "/projects/{project_id}/text/process",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Features 3 and 4: AI editing, translation and analysis",
)
def process_text(
    project_id: str, body: TextTaskRequest, container: Container
) -> JobAcceptedResponse:
    return _accept(
        container,
        JobCreate(
            type=JobType.TEXT_TASK,
            project_id=project_id,
            input=body.model_dump(exclude_none=True),
            provider=body.provider,
            model=body.model,
        ),
    )


@router.post(
    "/projects/{project_id}/subtitles/generate",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Feature 5: build structured subtitle cues from a transcript",
)
def generate_subtitles(
    project_id: str, body: GenerateSubtitleRequest, container: Container
) -> JobAcceptedResponse:
    return _accept(
        container,
        JobCreate(
            type=JobType.SUBTITLE_GENERATE,
            project_id=project_id,
            input=body.model_dump(exclude_none=True),
        ),
    )


@router.post(
    "/projects/{project_id}/subtitles/sync",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Feature 5: re-time an existing track against the video's audio",
)
def sync_subtitles(
    project_id: str, body: SyncSubtitleRequest, container: Container
) -> JobAcceptedResponse:
    """Automatic synchronisation. The manual counterpart is
    ``POST /api/projects/{id}/subtitles/{track_id}/retime``, which is pure
    arithmetic and therefore answers inline instead of as a job."""
    return _accept(
        container,
        JobCreate(
            type=JobType.SUBTITLE_SYNC,
            project_id=project_id,
            input=body.model_dump(exclude_none=True),
        ),
    )


@router.post(
    "/projects/{project_id}/subtitles/render",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Feature 5: burn subtitles into a new MP4",
)
def render_subtitles(
    project_id: str, body: RenderSubtitleRequest, container: Container
) -> JobAcceptedResponse:
    return _accept(
        container,
        JobCreate(
            type=JobType.SUBTITLE_RENDER,
            project_id=project_id,
            input=body.model_dump(exclude_none=True),
        ),
    )


@router.post(
    "/projects/{project_id}/speech/synthesize",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Feature 6: text to speech with structured pauses",
)
def synthesize_speech(
    project_id: str, body: SynthesizeSpeechRequest, container: Container
) -> JobAcceptedResponse:
    payload = body.model_dump(exclude_none=True)
    if body.segments is not None:
        payload["segments"] = [
            segment.model_dump(exclude_none=True) for segment in body.segments
        ]
    return _accept(
        container,
        JobCreate(
            type=JobType.TTS_SYNTHESIZE, project_id=project_id, input=payload
        ),
    )


# --------------------------------------------------------------------------
# Inspecting jobs
# --------------------------------------------------------------------------


@router.get("/jobs", response_model=ListResponse[Job])
def list_jobs(
    container: Container,
    project_id: Annotated[str | None, Query()] = None,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    type: Annotated[JobType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ListResponse[Job]:
    jobs = container.job_repo.list(
        project_id=project_id, status=status_filter, type=type, limit=limit, offset=offset
    )
    return ListResponse(items=jobs, total=len(jobs))


@router.get("/jobs/active", response_model=ListResponse[Job])
def list_active_jobs(container: Container) -> ListResponse[Job]:
    jobs = container.job_repo.list_active()
    return ListResponse(items=jobs, total=len(jobs))


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, container: Container) -> Job:
    job = container.job_repo.get(job_id)
    if job is None:
        raise NotFoundError(
            f"job {job_id!r} not found", user_message="وظیفه موردنظر پیدا نشد."
        )
    return job


@router.get("/jobs/{job_id}/logs", response_model=ListResponse[JobLogLine])
def get_job_logs(
    job_id: str,
    container: Container,
    limit: Annotated[int, Query(ge=1, le=20000)] = 5000,
) -> ListResponse[JobLogLine]:
    """Persisted console output. The live feed comes over SSE instead."""
    if container.job_repo.get(job_id) is None:
        raise NotFoundError(
            f"job {job_id!r} not found", user_message="وظیفه موردنظر پیدا نشد."
        )
    lines = container.job_repo.get_logs(job_id, limit=limit)
    return ListResponse(items=lines, total=len(lines))


@router.delete("/jobs/{job_id}", response_model=OperationResponse)
def cancel_job(job_id: str, container: Container) -> OperationResponse:
    """Request cancellation. Kills the external process tree if one is running."""
    job = container.job_repo.get(job_id)
    if job is None:
        raise NotFoundError(
            f"job {job_id!r} not found", user_message="وظیفه موردنظر پیدا نشد."
        )
    if job.status.is_terminal:
        raise ConflictError(
            f"job {job_id!r} is already {job.status.value}",
            user_message="این وظیفه پیش‌تر به پایان رسیده است.",
        )

    container.jobs.cancel(job_id)
    return OperationResponse(message="درخواست لغو ارسال شد.")


# --------------------------------------------------------------------------
# Live updates
# --------------------------------------------------------------------------


@router.get("/events", include_in_schema=False)
async def stream_events(request: Request) -> StreamingResponse:
    """Server-Sent Events carrying every job update.

    One connection serves the whole application; the client filters by job id.
    A comment line is sent periodically so proxies and the browser do not close
    an idle connection, and the loop exits as soon as the client disconnects.
    """
    container = get_container(request)
    queue = container.events.subscribe()

    async def generator():
        try:
            # Tell the client we are live so it can clear any "reconnecting" state.
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                payload = json.dumps(
                    event.model_dump(mode="json", exclude_none=True), ensure_ascii=False
                )
                yield f"event: job\ndata: {payload}\n\n"
        finally:
            container.events.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Disable proxy buffering, which would otherwise batch events.
            "X-Accel-Buffering": "no",
        },
    )

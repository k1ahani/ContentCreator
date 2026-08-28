"""Subtitle track and cue endpoints.

These power the timeline editor, so they are fine-grained on purpose: dragging
a cue edge is one ``PATCH`` on one cue, not a whole-track save. Split and merge
are dedicated endpoints because both need to renumber neighbours atomically,
which a generic update cannot express.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import Container, CurrentProject
from app.api.schemas.requests import (
    CreateCueRequest,
    CreateTrackRequest,
    ExportSubtitleRequest,
    MergeCuesRequest,
    SplitCueRequest,
    UpdateCueRequest,
    UpdateTrackRequest,
)
from app.api.schemas.responses import ListResponse, OperationResponse
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.domain.enums import AssetType, SubtitleFormat
from app.domain.subtitle import (
    CueCreate,
    CueUpdate,
    SubtitleCue,
    SubtitleTrack,
    TrackCreate,
)
from app.media.subtitles.formats import to_ass, to_srt, to_vtt, write_subtitle_file

logger = get_logger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/subtitles", tags=["subtitles"])

#: Minimum cue length. Prevents a drag from collapsing a cue to nothing.
MIN_CUE_DURATION = 0.1


def _require_track(container: Container, project_id: str, track_id: str) -> SubtitleTrack:
    track = container.subtitles.get_track(track_id)
    if track is None or track.project_id != project_id:
        raise NotFoundError(
            f"track {track_id!r} not in project {project_id!r}",
            user_message="زیرنویس موردنظر پیدا نشد.",
        )
    return track


def _require_cue(container: Container, track_id: str, cue_id: str) -> SubtitleCue:
    cue = container.subtitles.get_cue(cue_id)
    if cue is None or cue.track_id != track_id:
        raise NotFoundError(
            f"cue {cue_id!r} not in track {track_id!r}",
            user_message="قطعه زیرنویس موردنظر پیدا نشد.",
        )
    return cue


# --------------------------------------------------------------------------
# Tracks
# --------------------------------------------------------------------------


@router.get("", response_model=ListResponse[SubtitleTrack])
def list_tracks(project: CurrentProject, container: Container) -> ListResponse[SubtitleTrack]:
    tracks = container.subtitles.list_tracks(project.id)
    return ListResponse(items=tracks, total=len(tracks))


@router.post("", response_model=SubtitleTrack, status_code=status.HTTP_201_CREATED)
def create_track(
    project: CurrentProject, body: CreateTrackRequest, container: Container
) -> SubtitleTrack:
    track = container.subtitles.create_track(
        project.id,
        TrackCreate(
            name=body.name or f"زیرنویس {body.language.native_name}",
            language=body.language,
            style=body.style or container.settings.subtitle_style,
            source_document_id=body.source_document_id,
        ),
    )
    container.projects.touch(project.id)
    return track


@router.get("/{track_id}", response_model=SubtitleTrack)
def get_track(project: CurrentProject, track_id: str, container: Container) -> SubtitleTrack:
    return _require_track(container, project.id, track_id)


@router.patch("/{track_id}", response_model=SubtitleTrack)
def update_track(
    project: CurrentProject,
    track_id: str,
    body: UpdateTrackRequest,
    container: Container,
) -> SubtitleTrack:
    """Rename a track, change its language, or restyle it.

    Style changes are what the appearance panel writes, and they apply to the
    live preview and the render identically.
    """
    _require_track(container, project.id, track_id)
    updated = container.subtitles.update_track(
        track_id, name=body.name, language=body.language, style=body.style
    )
    assert updated is not None
    container.projects.touch(project.id)
    return updated


@router.delete("/{track_id}", response_model=OperationResponse)
def delete_track(
    project: CurrentProject, track_id: str, container: Container
) -> OperationResponse:
    _require_track(container, project.id, track_id)
    container.subtitles.delete_track(track_id)
    return OperationResponse(message="زیرنویس حذف شد.")


# --------------------------------------------------------------------------
# Cues
# --------------------------------------------------------------------------


@router.get("/{track_id}/cues", response_model=ListResponse[SubtitleCue])
def list_cues(
    project: CurrentProject, track_id: str, container: Container
) -> ListResponse[SubtitleCue]:
    _require_track(container, project.id, track_id)
    cues = container.subtitles.list_cues(track_id)
    return ListResponse(items=cues, total=len(cues))


@router.post(
    "/{track_id}/cues", response_model=SubtitleCue, status_code=status.HTTP_201_CREATED
)
def add_cue(
    project: CurrentProject,
    track_id: str,
    body: CreateCueRequest,
    container: Container,
) -> SubtitleCue:
    _require_track(container, project.id, track_id)
    if body.end - body.start < MIN_CUE_DURATION:
        raise ValidationError(
            f"cue is shorter than {MIN_CUE_DURATION}s",
            user_message="مدت زمان قطعه زیرنویس بسیار کوتاه است.",
        )
    cue = container.subtitles.add_cue(
        track_id, CueCreate(start=body.start, end=body.end, text=body.text, index=body.index)
    )
    container.projects.touch(project.id)
    return cue


@router.patch("/{track_id}/cues/{cue_id}", response_model=SubtitleCue)
def update_cue(
    project: CurrentProject,
    track_id: str,
    cue_id: str,
    body: UpdateCueRequest,
    container: Container,
) -> SubtitleCue:
    """Edit a cue's text or timing. This is the endpoint a timeline drag hits."""
    _require_track(container, project.id, track_id)
    cue = _require_cue(container, track_id, cue_id)

    start = body.start if body.start is not None else cue.start
    end = body.end if body.end is not None else cue.end
    if end - start < MIN_CUE_DURATION:
        raise ValidationError(
            f"resulting cue is shorter than {MIN_CUE_DURATION}s",
            user_message="زمان پایان باید بعد از زمان شروع باشد.",
        )

    updated = container.subtitles.update_cue(
        cue_id,
        CueUpdate(
            start=body.start, end=body.end, text=body.text,
            style_overrides=body.style_overrides,
        ),
    )
    assert updated is not None
    return updated


@router.delete("/{track_id}/cues/{cue_id}", response_model=OperationResponse)
def delete_cue(
    project: CurrentProject, track_id: str, cue_id: str, container: Container
) -> OperationResponse:
    _require_track(container, project.id, track_id)
    _require_cue(container, track_id, cue_id)
    container.subtitles.delete_cue(cue_id)
    return OperationResponse(message="قطعه زیرنویس حذف شد.")


@router.post("/{track_id}/cues/{cue_id}/split", response_model=ListResponse[SubtitleCue])
def split_cue(
    project: CurrentProject,
    track_id: str,
    cue_id: str,
    body: SplitCueRequest,
    container: Container,
) -> ListResponse[SubtitleCue]:
    """Split one cue into two at a timeline position.

    Text is divided at the nearest word boundary to the split point, in
    proportion to where the cut falls, unless explicit halves are supplied.
    """
    _require_track(container, project.id, track_id)
    cue = _require_cue(container, track_id, cue_id)

    at = body.at_seconds
    if not (cue.start + MIN_CUE_DURATION <= at <= cue.end - MIN_CUE_DURATION):
        raise ValidationError(
            f"split point {at} is not inside cue {cue.start}-{cue.end}",
            user_message="نقطه تقسیم باید داخل بازه این قطعه باشد.",
        )

    if body.first_text is not None and body.second_text is not None:
        first_text, second_text = body.first_text, body.second_text
    else:
        first_text, second_text = _split_text_proportionally(
            cue.text, (at - cue.start) / cue.duration
        )

    container.subtitles.update_cue(
        cue_id, CueUpdate(start=cue.start, end=at, text=first_text)
    )
    container.subtitles.add_cue(
        track_id,
        CueCreate(start=at, end=cue.end, text=second_text, index=cue.index + 1),
    )
    container.subtitles.reindex(track_id)
    container.projects.touch(project.id)

    cues = container.subtitles.list_cues(track_id)
    return ListResponse(items=cues, total=len(cues))


@router.post("/{track_id}/cues/{cue_id}/merge", response_model=ListResponse[SubtitleCue])
def merge_cue(
    project: CurrentProject,
    track_id: str,
    cue_id: str,
    body: MergeCuesRequest,
    container: Container,
) -> ListResponse[SubtitleCue]:
    """Merge a cue with the following one, spanning both time ranges."""
    _require_track(container, project.id, track_id)
    cue = _require_cue(container, track_id, cue_id)

    ordered = container.subtitles.list_cues(track_id)
    position = next((i for i, item in enumerate(ordered) if item.id == cue_id), -1)
    if position == -1 or position + 1 >= len(ordered):
        raise ValidationError(
            "no following cue to merge with",
            user_message="قطعه بعدی برای ادغام وجود ندارد.",
        )

    following = ordered[position + 1]
    merged_text = f"{cue.text.strip()}{body.separator}{following.text.strip()}".strip()

    container.subtitles.update_cue(
        cue_id, CueUpdate(start=cue.start, end=following.end, text=merged_text)
    )
    container.subtitles.delete_cue(following.id)
    container.subtitles.reindex(track_id)
    container.projects.touch(project.id)

    cues = container.subtitles.list_cues(track_id)
    return ListResponse(items=cues, total=len(cues))


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


@router.get("/{track_id}/preview")
def preview_subtitle(
    project: CurrentProject,
    track_id: str,
    container: Container,
    format: Annotated[SubtitleFormat, Query()] = SubtitleFormat.SRT,
) -> Response:
    """Serialised subtitle text, for the preview pane and for copying."""
    track = _require_track(container, project.id, track_id)
    if format is SubtitleFormat.SRT:
        body = to_srt(track.cues)
    elif format is SubtitleFormat.VTT:
        body = to_vtt(track.cues)
    else:
        body = to_ass(track.cues, track.style)
    return Response(content=body, media_type="text/plain; charset=utf-8")


@router.post("/{track_id}/export", response_model=OperationResponse)
def export_subtitle(
    project: CurrentProject,
    track_id: str,
    body: ExportSubtitleRequest,
    container: Container,
) -> OperationResponse:
    """Write a subtitle file into the project and register it as an asset."""
    track = _require_track(container, project.id, track_id)
    if not track.cues:
        raise ValidationError(
            "track has no cues to export",
            user_message="این زیرنویس هیچ قطعه‌ای ندارد.",
        )

    from app.core.paths import PATHS  # local import: keeps the router light

    directory = PATHS.project_subdir(project.id, "subtitles")
    stem = track.name or "subtitle"
    path = write_subtitle_file(
        directory / f"{stem}.{body.format.value}", track.cues, track.style
    )

    container.assets.create(
        project_id=project.id,
        type=AssetType.SUBTITLE,
        path=path,
        original_filename=path.name,
        size_bytes=path.stat().st_size,
        format=body.format.value,
        metadata={"track_id": track_id, "cue_count": len(track.cues)},
    )
    container.projects.touch(project.id)
    return OperationResponse(message=f"فایل {path.name} ذخیره شد.")


def _split_text_proportionally(text: str, ratio: float) -> tuple[str, str]:
    """Split text at the word boundary closest to ``ratio`` through it."""
    words = text.split()
    if len(words) < 2:
        return text, ""

    target = max(1, min(len(words) - 1, round(len(words) * ratio)))
    return " ".join(words[:target]), " ".join(words[target:])

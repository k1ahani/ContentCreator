"""System status, settings and file serving."""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, Response

from app.api.deps import Container
from app.api.schemas.requests import ResetSettingsRequest, UpdateSettingsRequest
from app.api.schemas.responses import (
    AudioPresetInfo,
    DependencyStatus,
    MediaCapabilitiesResponse,
    OperationResponse,
    RenderQualityInfo,
    SettingsResponse,
    SystemStatusResponse,
)
from app.core.errors import NotFoundError, PathTraversalError
from app.core.logging import get_logger
from app.core.paths import PATHS
from app.core.security import is_within
from app.media.audio import AUDIO_PRESETS
from app.media.video import RENDER_QUALITIES
from app.services.settings import DEFAULTS

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["system"])


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------


@router.get("/system/status", response_model=SystemStatusResponse)
def system_status(container: Container) -> SystemStatusResponse:
    """The dependency doctor.

    Rendered on the dashboard and on the settings page. Every external tool the
    platform needs reports here with a Persian explanation and a fix, so a
    missing dependency is discovered on arrival rather than when a button fails.
    """
    from app import __version__

    dependencies: list[DependencyStatus] = []

    # -- FFmpeg (required) -------------------------------------------------
    tools = container.find_ffmpeg()
    dependencies.append(
        DependencyStatus(
            id="ffmpeg",
            label_fa="FFmpeg",
            available=tools is not None,
            required=True,
            version=tools.version if tools else None,
            path=str(tools.ffmpeg) if tools else None,
            detail_fa=(
                f"از مسیر {tools.source} بارگذاری شد."
                if tools
                else "برای استخراج صدا و رندر ویدیو لازم است."
            ),
            hint_fa=None if tools else "اسکریپت scripts/setup.ps1 را اجرا کنید.",
        )
    )

    # -- Claude CLI (required for AI features) -----------------------------
    provider_info = next(
        (info for info in container.ai.list_providers() if info.id == "claude"), None
    )
    dependencies.append(
        DependencyStatus(
            id="claude_cli",
            label_fa="Claude CLI",
            available=bool(provider_info and provider_info.available),
            required=True,
            version=provider_info.version if provider_info else None,
            path=provider_info.executable_path if provider_info else None,
            detail_fa=(
                "برای ویرایش، ترجمه و بازبینی متن استفاده می‌شود."
                if provider_info and provider_info.available
                else (provider_info.unavailable_reason if provider_info else None)
            ),
            hint_fa=(
                None
                if provider_info and provider_info.available
                else "مسیر Claude CLI را در تنظیمات وارد کنید."
            ),
        )
    )

    # -- Speech recognition (optional) -------------------------------------
    engines = container.transcription.info_all()
    engine = engines[0] if engines else None
    dependencies.append(
        DependencyStatus(
            id="asr",
            label_fa="موتور تبدیل گفتار به متن",
            available=bool(engine and engine.available),
            required=False,
            version=engine.version if engine else None,
            detail_fa=(
                "به‌صورت محلی و آفلاین اجرا می‌شود."
                if engine and engine.available
                else (engine.unavailable_reason if engine else None)
            ),
            hint_fa=(engine.hint if engine and not engine.available else None),
        )
    )

    # -- Text to speech (optional) -----------------------------------------
    for info in container.tts.info_all():
        dependencies.append(
            DependencyStatus(
                id=f"tts_{info.id}",
                label_fa=info.display_name,
                available=info.available,
                required=False,
                detail_fa=(
                    ("آفلاین" if info.offline else "نیازمند اینترنت")
                    if info.available
                    else info.unavailable_reason
                ),
                hint_fa=info.hint,
            )
        )

    ready = all(dep.available for dep in dependencies if dep.required)

    return SystemStatusResponse(
        ready=ready,
        app_version=__version__,
        python_version=sys.version.split()[0],
        platform=f"{platform.system()} {platform.release()}",
        dependencies=dependencies,
        workspace_path=str(PATHS.projects),
        database_path=str(container.config.database_path),
        active_jobs=container.jobs.active_count,
        queued_jobs=container.jobs.pending_count,
    )


@router.get("/system/media", response_model=MediaCapabilitiesResponse)
def media_capabilities(container: Container) -> MediaCapabilitiesResponse:
    """Audio presets and render qualities, with their Persian descriptions."""
    tools = container.find_ffmpeg()
    return MediaCapabilitiesResponse(
        audio_presets=[
            AudioPresetInfo(
                id=preset.id,
                label_fa=preset.label_fa,
                extension=preset.extension,
                approx_mb_per_hour=preset.approx_mb_per_hour,
                description_fa=preset.description_fa,
                sample_rate=preset.sample_rate,
            )
            for preset in AUDIO_PRESETS.values()
        ],
        render_qualities=[
            RenderQualityInfo(
                id=quality.id,
                label_fa=quality.label_fa,
                description_fa=quality.description_fa,
                crf=quality.crf,
            )
            for quality in RENDER_QUALITIES.values()
        ],
        ffmpeg_available=tools is not None,
        ffmpeg_version=tools.version if tools else None,
    )


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


@router.get("/settings", response_model=SettingsResponse)
def get_settings(container: Container) -> SettingsResponse:
    settings = container.settings
    return SettingsResponse(
        values=settings.all(), grouped=settings.grouped(), defaults=dict(DEFAULTS)
    )


@router.put("/settings", response_model=SettingsResponse)
def update_settings(body: UpdateSettingsRequest, container: Container) -> SettingsResponse:
    """Validate and persist settings, then invalidate whatever they affect.

    Invalidation is what makes a changed CLI or FFmpeg path take effect
    immediately instead of at the next restart.
    """
    settings = container.settings
    settings.update(body.values)
    container.invalidate(keys=list(body.values))
    return SettingsResponse(
        values=settings.all(), grouped=settings.grouped(), defaults=dict(DEFAULTS)
    )


@router.post("/settings/reset", response_model=SettingsResponse)
def reset_settings(body: ResetSettingsRequest, container: Container) -> SettingsResponse:
    settings = container.settings
    settings.reset(body.key)
    container.invalidate(keys=[body.key] if body.key else None)
    return SettingsResponse(
        values=settings.all(), grouped=settings.grouped(), defaults=dict(DEFAULTS)
    )


# --------------------------------------------------------------------------
# File serving
# --------------------------------------------------------------------------


@router.get("/files/{asset_id}", include_in_schema=False)
def serve_asset(asset_id: str, container: Container, request: Request) -> Response:
    """Stream an asset to the browser.

    Range requests matter here: the subtitle timeline's video player has to
    seek, and a player cannot seek in a response that does not advertise range
    support. Starlette's ``FileResponse`` handles ``Range`` itself, so this
    endpoint's own job is authorisation and content typing.

    Serving is restricted to files inside a project workspace **or** files
    still registered as an asset, so this cannot become an arbitrary file read.
    """
    asset = container.assets.get(asset_id)
    if asset is None:
        raise NotFoundError(
            f"asset {asset_id!r} not found", user_message="فایل موردنظر پیدا نشد."
        )

    path = Path(asset.path)
    if not path.is_file():
        raise NotFoundError(
            f"asset file is missing: {path}",
            user_message="فایل روی دیسک پیدا نشد. ممکن است جابه‌جا یا حذف شده باشد.",
        )

    # A source video imported in place lives outside the workspace, which is
    # legitimate. Anything else must be inside it.
    workspace = PATHS.project_dir(asset.project_id)
    imported_from = asset.metadata.get("imported_from")
    if not is_within(workspace, path) and str(path) != str(imported_from):
        raise PathTraversalError(
            f"refusing to serve {path}: outside the project workspace",
        )

    return FileResponse(
        path,
        media_type=_media_type(path),
        filename=asset.original_filename,
        content_disposition_type="inline",
    )


#: Extensions the browser plays natively, mapped to the type it expects.
_MEDIA_TYPES: dict[str, str] = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".srt": "text/plain; charset=utf-8",
    ".vtt": "text/vtt; charset=utf-8",
    ".ass": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def _media_type(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


@router.get("/files/{asset_id}/download", include_in_schema=False)
def download_asset(asset_id: str, container: Container) -> Response:
    """Same file, but as an attachment so the browser saves it."""
    asset = container.assets.get(asset_id)
    if asset is None:
        raise NotFoundError(
            f"asset {asset_id!r} not found", user_message="فایل موردنظر پیدا نشد."
        )
    path = Path(asset.path)
    if not path.is_file():
        raise NotFoundError(
            f"asset file is missing: {path}", user_message="فایل روی دیسک پیدا نشد."
        )
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=asset.original_filename,
        content_disposition_type="attachment",
    )


@router.get("/system/browse", include_in_schema=False)
def browse_filesystem(
    container: Container,
    path: Annotated[str | None, Query(max_length=4096)] = None,
) -> dict:
    """List drives and directories so the UI can offer a file picker.

    A browser cannot give a web page a real filesystem path from its own file
    dialog, and picking a 4 GB video should not mean uploading it. This exposes
    a read-only listing, restricted to directories and media files, so the user
    can navigate to a file and hand its path to the import endpoint.
    """
    if not path:
        # Drive roots.
        entries = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:/")
            if drive.exists():
                entries.append({"name": f"{letter}:", "path": str(drive), "type": "drive"})
        return {"current": None, "parent": None, "entries": entries}

    target = Path(path).expanduser()
    if not target.is_dir():
        raise NotFoundError(
            f"not a directory: {target}", user_message="این پوشه وجود ندارد."
        )

    from app.api.routers.projects import ALLOWED_EXTENSIONS

    media_extensions = {
        ext for extensions in ALLOWED_EXTENSIONS.values() for ext in extensions
    }

    entries: list[dict] = []
    try:
        for child in sorted(
            target.iterdir(), key=lambda item: (item.is_file(), item.name.lower())
        ):
            try:
                if child.is_dir():
                    entries.append({"name": child.name, "path": str(child), "type": "directory"})
                elif child.suffix.lower() in media_extensions:
                    entries.append(
                        {
                            "name": child.name,
                            "path": str(child),
                            "type": "file",
                            "size": child.stat().st_size,
                            "extension": child.suffix.lower(),
                        }
                    )
            except OSError:
                continue  # unreadable entry: skip rather than fail the listing
    except PermissionError:
        raise NotFoundError(
            f"permission denied: {target}",
            user_message="دسترسی به این پوشه وجود ندارد.",
        ) from None

    return {
        "current": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "entries": entries[:1000],
    }

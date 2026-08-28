"""Project, asset and document endpoints.

Projects are the organising unit: assets and documents are always addressed
through their project, which keeps workspace paths derivable from the URL and
makes an orphaned file impossible.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, UploadFile, File, status

from app.api.deps import Container, CurrentProject
from app.api.schemas.requests import (
    CreateDocumentRequest,
    CreateProjectRequest,
    ImportAssetRequest,
    UpdateDocumentRequest,
    UpdateProjectRequest,
)
from app.api.schemas.responses import (
    ImportedAssetResponse,
    ListResponse,
    OperationResponse,
)
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.paths import PATHS
from app.core.security import sanitize_filename, unique_path, validate_import_path
from app.domain.asset import MediaAsset
from app.domain.document import DocumentCreate, DocumentUpdate, TextDocument
from app.domain.enums import AssetType, DocumentType, ProjectStatus
from app.domain.project import Project, ProjectCreate, ProjectUpdate

logger = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

#: Extensions accepted per asset type. This is the allowlist that keeps an
#: arbitrary path from being registered as media.
ALLOWED_EXTENSIONS: dict[AssetType, tuple[str, ...]] = {
    AssetType.VIDEO: (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg"),
    AssetType.AUDIO: (".mp3", ".wav", ".ogg", ".opus", ".m4a", ".aac", ".flac", ".wma"),
    AssetType.SUBTITLE: (".srt", ".vtt", ".ass"),
    AssetType.TRANSCRIPT: (".txt", ".md"),
    AssetType.VOICE: (".mp3", ".wav", ".ogg"),
    AssetType.RENDERED_VIDEO: (".mp4",),
}


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------


@router.get("", response_model=ListResponse[Project])
def list_projects(
    container: Container,
    status_filter: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ListResponse[Project]:
    projects = container.projects.list(
        status=status_filter, search=search, limit=limit, offset=offset
    )
    return ListResponse(items=projects, total=container.projects.count(status=status_filter))


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
def create_project(body: CreateProjectRequest, container: Container) -> Project:
    project = container.projects.create(
        ProjectCreate(name=body.name, description=body.description)
    )
    # The workspace tree is created eagerly so every later write can assume it.
    PATHS.ensure_project_dirs(project.id)
    logger.info("created project %s (%s)", project.id, project.name)
    return project


@router.get("/{project_id}", response_model=Project)
def get_project(project: CurrentProject) -> Project:
    return project


@router.patch("/{project_id}", response_model=Project)
def update_project(
    project: CurrentProject, body: UpdateProjectRequest, container: Container
) -> Project:
    updated = container.projects.update(
        project.id,
        ProjectUpdate(name=body.name, description=body.description, status=body.status),
    )
    assert updated is not None
    return updated


@router.delete("/{project_id}", response_model=OperationResponse)
def delete_project(
    project: CurrentProject,
    container: Container,
    delete_files: Annotated[bool, Query()] = False,
) -> OperationResponse:
    """Delete a project. Workspace files are kept unless asked for explicitly."""
    container.projects.delete(project.id)

    if delete_files:
        workspace = PATHS.project_dir(project.id)
        if workspace.is_dir():
            shutil.rmtree(workspace, ignore_errors=True)
            logger.info("removed workspace for project %s", project.id)

    return OperationResponse(
        message="پروژه حذف شد." if not delete_files else "پروژه و فایل‌های آن حذف شدند."
    )


# --------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------


@router.get("/{project_id}/assets", response_model=ListResponse[MediaAsset])
def list_assets(
    project: CurrentProject,
    container: Container,
    type: Annotated[AssetType | None, Query()] = None,
) -> ListResponse[MediaAsset]:
    assets = container.assets.list_for_project(project.id, type=type)
    return ListResponse(items=assets, total=len(assets))


@router.post(
    "/{project_id}/assets/import",
    response_model=ImportedAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_asset(
    project: CurrentProject, body: ImportAssetRequest, container: Container
) -> ImportedAssetResponse:
    """Register a file the user selected from their Windows filesystem.

    The path is validated against an extension allowlist, a size cap and the
    optional import roots from Settings before anything touches it.
    """
    settings = container.settings
    extensions = ALLOWED_EXTENSIONS.get(body.type, ())

    source = validate_import_path(
        body.path,
        allowed_extensions=extensions,
        allowed_roots=settings.allowed_import_roots,
        max_bytes=settings.max_import_bytes,
    )

    target = source
    if body.copy_into_project:
        destination_dir = PATHS.project_subdir(project.id, body.type.subdir)
        target = unique_path(destination_dir, source.name)
        shutil.copy2(source, target)
        logger.info("copied %s into project %s", source.name, project.id)

    probe = None
    duration = None
    metadata: dict = {"imported_from": str(source)}
    if body.type in (AssetType.VIDEO, AssetType.AUDIO, AssetType.VOICE, AssetType.RENDERED_VIDEO):
        tools = container.find_ffmpeg()
        if tools is not None:
            from app.media.ffmpeg.probe import probe_media  # local: optional path

            probe = probe_media(tools, target)
            duration = probe.duration_seconds
            metadata.update(probe.model_dump(exclude_none=True))

    asset = container.assets.create(
        project_id=project.id,
        type=body.type,
        path=target,
        original_filename=source.name,
        size_bytes=target.stat().st_size,
        format=target.suffix.lstrip(".").lower(),
        duration_seconds=duration,
        metadata=metadata,
    )
    container.projects.touch(project.id)
    return ImportedAssetResponse(asset=asset, probe=probe)


@router.post(
    "/{project_id}/assets/upload",
    response_model=ImportedAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    project: CurrentProject,
    container: Container,
    file: Annotated[UploadFile, File()],
    type: Annotated[AssetType, Query()] = AssetType.VIDEO,
) -> ImportedAssetResponse:
    """Upload a file through the browser.

    Streamed to disk in chunks: reading a multi-gigabyte video into memory
    would defeat the point of keeping media on disk.
    """
    filename = sanitize_filename(file.filename or "upload")
    extensions = ALLOWED_EXTENSIONS.get(type, ())
    if Path(filename).suffix.lower() not in extensions:
        raise ValidationError(
            f"extension {Path(filename).suffix!r} not allowed for {type.value}",
            user_message="فرمت این فایل پشتیبانی نمی‌شود.",
            details={"allowed": list(extensions)},
        )

    destination = unique_path(PATHS.project_subdir(project.id, type.subdir), filename)
    limit = container.settings.max_import_bytes
    written = 0

    try:
        with destination.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise ValidationError(
                        f"upload exceeded {limit} bytes",
                        user_message="حجم فایل بیشتر از حد مجاز است.",
                    )
                handle.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    if written == 0:
        destination.unlink(missing_ok=True)
        raise ValidationError("uploaded file is empty", user_message="فایل ارسالی خالی است.")

    probe = None
    duration = None
    metadata: dict = {}
    if type in (AssetType.VIDEO, AssetType.AUDIO, AssetType.VOICE, AssetType.RENDERED_VIDEO):
        tools = container.find_ffmpeg()
        if tools is not None:
            from app.media.ffmpeg.probe import probe_media  # local: optional path

            probe = probe_media(tools, destination)
            duration = probe.duration_seconds
            metadata.update(probe.model_dump(exclude_none=True))

    asset = container.assets.create(
        project_id=project.id,
        type=type,
        path=destination,
        original_filename=filename,
        size_bytes=written,
        format=destination.suffix.lstrip(".").lower(),
        duration_seconds=duration,
        metadata=metadata,
    )
    container.projects.touch(project.id)
    return ImportedAssetResponse(asset=asset, probe=probe)


@router.delete("/{project_id}/assets/{asset_id}", response_model=OperationResponse)
def delete_asset(
    project: CurrentProject,
    asset_id: str,
    container: Container,
    delete_file: Annotated[bool, Query()] = False,
) -> OperationResponse:
    asset = container.assets.get(asset_id)
    if asset is None or asset.project_id != project.id:
        raise NotFoundError(
            f"asset {asset_id!r} not in project {project.id!r}",
            user_message="فایل موردنظر در این پروژه پیدا نشد.",
        )

    container.assets.delete(asset_id)

    if delete_file:
        path = Path(asset.path)
        # Only ever delete inside the project's own workspace: an imported
        # source file lives in the user's own directories and is not ours.
        workspace = PATHS.project_dir(project.id)
        try:
            path.resolve().relative_to(workspace.resolve())
        except ValueError:
            logger.info("not deleting %s: outside the project workspace", path)
        else:
            path.unlink(missing_ok=True)

    return OperationResponse(message="فایل حذف شد.")


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------


@router.get("/{project_id}/documents", response_model=ListResponse[TextDocument])
def list_documents(
    project: CurrentProject,
    container: Container,
    type: Annotated[DocumentType | None, Query()] = None,
) -> ListResponse[TextDocument]:
    documents = container.documents.list_for_project(project.id, type=type)
    return ListResponse(items=documents, total=len(documents))


@router.post(
    "/{project_id}/documents",
    response_model=TextDocument,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    project: CurrentProject, body: CreateDocumentRequest, container: Container
) -> TextDocument:
    document = container.documents.create(
        project.id,
        DocumentCreate(
            type=body.type,
            title=body.title,
            content=body.content,
            language=body.language,
            source_document_id=body.source_document_id,
        ),
    )
    container.projects.touch(project.id)
    return document


@router.get("/{project_id}/documents/{document_id}", response_model=TextDocument)
def get_document(
    project: CurrentProject, document_id: str, container: Container
) -> TextDocument:
    document = container.documents.get(document_id)
    if document is None or document.project_id != project.id:
        raise NotFoundError(
            f"document {document_id!r} not in project {project.id!r}",
            user_message="سند موردنظر پیدا نشد.",
        )
    return document


@router.patch("/{project_id}/documents/{document_id}", response_model=TextDocument)
def update_document(
    project: CurrentProject,
    document_id: str,
    body: UpdateDocumentRequest,
    container: Container,
) -> TextDocument:
    existing = container.documents.get(document_id)
    if existing is None or existing.project_id != project.id:
        raise NotFoundError(
            f"document {document_id!r} not in project {project.id!r}",
            user_message="سند موردنظر پیدا نشد.",
        )
    updated = container.documents.update(
        document_id,
        DocumentUpdate(title=body.title, content=body.content, language=body.language),
    )
    assert updated is not None
    container.projects.touch(project.id)
    return updated


@router.delete("/{project_id}/documents/{document_id}", response_model=OperationResponse)
def delete_document(
    project: CurrentProject, document_id: str, container: Container
) -> OperationResponse:
    existing = container.documents.get(document_id)
    if existing is None or existing.project_id != project.id:
        raise NotFoundError(
            f"document {document_id!r} not in project {project.id!r}",
            user_message="سند موردنظر پیدا نشد.",
        )
    container.documents.delete(document_id)
    return OperationResponse(message="سند حذف شد.")

"""FastAPI dependencies.

The container is created once in the lifespan handler and stored on
``app.state``. These helpers pull it back out and expose the pieces routers
need, so a router never imports the container module directly and stays easy to
test with a stub.

There is no authentication dependency anywhere in this application by design:
it is a single-user local tool (see docs/ARCHITECTURE.md).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Path, Request

from app.container import ServiceContainer
from app.core.errors import NotFoundError
from app.domain.project import Project


def get_container(request: Request) -> ServiceContainer:
    """The application's service container."""
    container = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - startup guarantees this
        raise RuntimeError("service container is not initialised")
    return container


Container = Annotated[ServiceContainer, Depends(get_container)]


def get_project(
    project_id: Annotated[str, Path(min_length=1, max_length=64)],
    container: Container,
) -> Project:
    """Resolve a project id from the path, 404-ing in Persian when missing."""
    project = container.projects.get(project_id)
    if project is None:
        raise NotFoundError(
            f"project {project_id!r} not found",
            user_message="پروژه موردنظر پیدا نشد.",
        )
    return project


CurrentProject = Annotated[Project, Depends(get_project)]

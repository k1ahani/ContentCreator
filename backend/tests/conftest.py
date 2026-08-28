"""Shared test fixtures.

Design notes:

* The database is a real SQLite file in ``tmp_path``, migrated the same way
  production is. Mocking the database would test the mock, not the schema.
* Project workspaces are created under the real ``storage/projects`` tree
  because ``AppPaths`` is a module-level singleton that other modules import by
  value; rebinding it in one module would not affect the rest. Instead every
  workspace a test creates is tracked and removed afterwards, which keeps the
  tree clean without pretending the path layer is injectable.
* External-tool tests are skipped, not failed, when the tool is absent, so the
  suite is still useful on a machine without FFmpeg or the Claude CLI.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.container import ServiceContainer
from app.core.config import AppConfig
from app.core.logging import setup_logging
from app.core.paths import PATHS
from app.domain.project import Project, ProjectCreate
from app.media.ffmpeg import find_ffmpeg

setup_logging("WARNING")


@pytest.fixture(scope="session")
def ffmpeg_tools():
    """Real FFmpeg tools, or skip the test."""
    tools = find_ffmpeg()
    if tools is None:
        pytest.skip("FFmpeg is not installed; run scripts/setup.ps1")
    return tools


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        database_path=tmp_path / "test.db",
        job_workers=2,
        serve_frontend=False,
        log_level="WARNING",
    )


@pytest.fixture
def container(config: AppConfig) -> Iterator[ServiceContainer]:
    """A fully wired container against a temporary database."""
    instance = ServiceContainer(config)
    instance.startup()
    created: list[str] = []

    # Remember every project so its workspace can be removed afterwards.
    original_create = instance.projects.create

    try:
        yield instance
    finally:
        for project in instance.projects.list(limit=200):
            created.append(project.id)
        instance.shutdown()
        for project_id in created:
            shutil.rmtree(PATHS.project_dir(project_id), ignore_errors=True)


@pytest.fixture
def project(container: ServiceContainer) -> Project:
    """A project with its workspace directories created."""
    created = container.projects.create(
        ProjectCreate(name="پروژه آزمایشی", description="برای تست")
    )
    PATHS.ensure_project_dirs(created.id)
    return created


@pytest.fixture
def client(container: ServiceContainer):
    """A TestClient wired to the same container the test can inspect.

    The lifespan is bypassed deliberately: the container fixture already owns
    startup and shutdown, and running both would migrate twice and start two
    worker pools.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(container.config)
    app.state.container = container
    app.router.lifespan_context = _null_lifespan

    with TestClient(app) as test_client:
        # SSE publishing needs a bound loop; TestClient runs its own.
        yield test_client


def _null_lifespan(_app):
    """No-op lifespan so TestClient does not re-run startup."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def noop(_):
        yield

    return noop(_app)


@pytest.fixture
def sample_video(ffmpeg_tools, project: Project) -> Path:
    """A real 4-second H.264 + AAC file inside the project workspace."""
    from app.media.ffmpeg import run_ffmpeg

    path = PATHS.project_subdir(project.id, "source") / "sample.mp4"
    run_ffmpeg(
        ffmpeg_tools,
        [
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        output_path=path,
    )
    return path


@pytest.fixture
def video_asset(container: ServiceContainer, project: Project, sample_video: Path):
    """The sample video registered as a project asset."""
    from app.domain.enums import AssetType

    return container.assets.create(
        project_id=project.id,
        type=AssetType.VIDEO,
        path=sample_video,
        original_filename=sample_video.name,
        size_bytes=sample_video.stat().st_size,
        format="mp4",
        duration_seconds=4.0,
    )


def wait_for_job(container: ServiceContainer, job_id: str, timeout: float = 120.0):
    """Block until a job reaches a terminal state, then return it."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = container.job_repo.get(job_id)
        if job is not None and job.status.is_terminal:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")

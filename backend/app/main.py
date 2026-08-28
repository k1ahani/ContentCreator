"""FastAPI application factory and entry point.

Run with::

    python -m app.main
    # or
    uvicorn app.main:app

There is **no authentication anywhere in this application**. It is a
single-user tool bound to the loopback interface, and the requirement is
explicit that it must open straight to the dashboard. Security effort goes
where it actually matters for a local tool: path traversal, filename
sanitisation, extension allowlists, and never handing user input to a shell.
See ``app/core/security.py``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.errors import register_error_handlers
from app.api.routers import ai, jobs, projects, subtitles, system
from app.container import ServiceContainer
from app.core.config import AppConfig, get_config
from app.core.logging import get_logger, setup_logging
from app.core.paths import PATHS

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the container on startup, tear it down on shutdown."""
    config: AppConfig = app.state.config

    container = ServiceContainer(config)
    app.state.container = container

    # The event bus marshals events from worker threads onto this loop.
    container.events.bind_loop(asyncio.get_running_loop())
    container.startup()

    logger.info("listening on %s", config.base_url)
    try:
        yield
    finally:
        container.shutdown()


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Build the application. Tests call this with their own config."""
    config = config or get_config()
    setup_logging(config.log_level)

    app = FastAPI(
        title="Local AI Content Creator Platform",
        description=(
            "Local, single-user content production platform. "
            "Persian RTL interface, Claude via the local CLI, FFmpeg media pipeline."
        ),
        version=__version__,
        lifespan=lifespan,
        # No auth, so the docs are simply available.
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.config = config

    # The Vite dev server runs on a different port during development. In
    # production the frontend is served from this same origin, so CORS is not
    # involved at all.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[config.frontend_dev_origin, "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(system.router)
    app.include_router(projects.router)
    app.include_router(jobs.router)
    app.include_router(subtitles.router)
    app.include_router(ai.router)

    @app.get("/api/health", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    if config.serve_frontend:
        _mount_frontend(app)

    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built frontend, if it has been built.

    Missing build is not an error: during development the Vite dev server
    serves the UI instead. The placeholder response says so in Persian rather
    than returning a bare 404 that looks like a broken install.
    """
    dist = PATHS.frontend / "dist"
    index = dist / "index.html"

    if not index.is_file():
        logger.info("frontend build not found at %s; serving API only", dist)

        @app.get("/", include_in_schema=False)
        def frontend_missing() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "frontend_not_built",
                        "message": "رابط کاربری هنوز ساخته نشده است.",
                        "hint": "در پوشه frontend دستور npm install و سپس npm run build را اجرا کنید.",
                    }
                },
            )

        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:
        """Serve the SPA, letting the client router own unknown paths.

        A real file is returned when one exists (favicon, fonts); everything
        else falls through to ``index.html`` so a deep link such as
        ``/projects/abc/subtitles`` works on a hard refresh.
        """
        candidate = dist / full_path
        if full_path and candidate.is_file() and _is_inside(dist, candidate):
            return FileResponse(candidate)
        return FileResponse(index)

    logger.info("serving frontend from %s", dist)


def _is_inside(base: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


app = create_app()


def find_free_port(host: str, preferred: int, attempts: int = 20) -> int:
    """Return a bindable port, starting at ``preferred``.

    Windows reserves blocks of ports for Hyper-V/WinNAT. Binding inside one
    fails with WinError 10013 ("access forbidden") even though nothing is
    listening, which looks like a permissions problem and is not. Probing here
    turns a confusing crash into an automatic, logged recovery.
    """
    import socket

    for offset in range(attempts + 1):
        candidate = preferred + offset
        if candidate > 65535:
            break
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, candidate))
            except OSError:
                continue
        if offset:
            logger.warning(
                "port %d is not available on this machine, using %d instead",
                preferred,
                candidate,
            )
        return candidate

    raise SystemExit(
        f"No free port found between {preferred} and {preferred + attempts}. "
        f"Set CCA_PORT to a port outside the ranges listed by "
        f"'netsh interface ipv4 show excludedportrange protocol=tcp'."
    )


def main() -> None:
    """Console entry point used by the start scripts."""
    import uvicorn

    config = get_config()
    port = find_free_port(config.host, config.port, config.port_fallback_attempts)
    uvicorn.run(
        "app.main:app",
        host=config.host,
        port=port,
        log_level=config.log_level.lower(),
        # Reload is a development convenience only; the start scripts do not
        # enable it because it would restart the job workers mid-render.
        reload=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()

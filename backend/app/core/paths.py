"""Filesystem layout of the platform.

Single source of truth for *where things live on disk*. Nothing else in the
codebase may hardcode an absolute path; everything resolves through `AppPaths`.

Layout (relative to the repository root)::

    <root>/
      backend/          backend source + virtualenv
      frontend/         frontend source
      bin/ffmpeg/       bundled FFmpeg binaries (optional)
      config/           bootstrap configuration + local overrides
      logs/             rotating application logs
      storage/
        projects/<project-id>/
          source/       user-provided originals (never modified)
          audio/        extracted / generated audio
          transcript/   transcripts and intermediate text artefacts
          subtitles/    subtitle exports (srt/vtt/ass)
          voice/        text-to-speech output
          rendered/     final rendered video
          temp/         scratch space, safe to delete
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

# <root>/backend/app/core/paths.py -> parents[3] == <root>
_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: Sub-directories created inside every project workspace.
PROJECT_SUBDIRS: Final[tuple[str, ...]] = (
    "source",
    "audio",
    "transcript",
    "subtitles",
    "voice",
    "rendered",
    "temp",
)


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Resolved absolute paths for every platform-managed directory."""

    root: Path

    @property
    def backend(self) -> Path:
        return self.root / "backend"

    @property
    def frontend(self) -> Path:
        return self.root / "frontend"

    @property
    def bin_dir(self) -> Path:
        return self.root / "bin"

    @property
    def bundled_ffmpeg_dir(self) -> Path:
        return self.bin_dir / "ffmpeg"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def storage(self) -> Path:
        return self.root / "storage"

    @property
    def projects(self) -> Path:
        return self.storage / "projects"

    @property
    def database_file(self) -> Path:
        return self.storage / "app.db"

    @property
    def models_cache(self) -> Path:
        """Cache directory for downloaded speech-recognition model weights."""
        return self.storage / "models"

    def project_dir(self, project_id: str) -> Path:
        """Workspace directory of a single project."""
        return self.projects / project_id

    def project_subdir(self, project_id: str, subdir: str) -> Path:
        if subdir not in PROJECT_SUBDIRS:
            raise ValueError(f"unknown project subdirectory: {subdir!r}")
        return self.project_dir(project_id) / subdir

    def ensure_base_dirs(self) -> None:
        """Create the directories the platform always needs."""
        for path in (
            self.config_dir,
            self.logs_dir,
            self.storage,
            self.projects,
            self.models_cache,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def ensure_project_dirs(self, project_id: str) -> Path:
        """Create (idempotently) the full workspace tree for one project."""
        base = self.project_dir(project_id)
        for subdir in PROJECT_SUBDIRS:
            (base / subdir).mkdir(parents=True, exist_ok=True)
        return base


#: Process-wide singleton. Import this rather than constructing `AppPaths`.
PATHS: Final[AppPaths] = AppPaths(root=_ROOT)

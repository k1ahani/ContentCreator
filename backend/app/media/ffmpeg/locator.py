"""FFmpeg discovery.

Resolution order, first working hit wins:

1. the path saved in Settings (``media.ffmpeg_path``);
2. the ``FFMPEG_PATH`` environment variable;
3. the build bundled with the project in ``bin/ffmpeg/`` - what
   ``scripts/setup.ps1`` installs, and the normal case on this machine;
4. ``ffmpeg`` on ``PATH``.

The bundled copy is preferred over ``PATH`` on purpose: it is version-pinned
with the project, so a system-wide FFmpeg upgrade cannot change rendering
behaviour underneath the user.

``ffprobe`` is resolved alongside ``ffmpeg`` from the same directory, because a
mismatched pair is a confusing failure mode.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.errors import FFmpegNotFoundError
from app.core.logging import get_logger
from app.core.paths import PATHS
from app.process import probe_executable

logger = get_logger(__name__)

_EXE = ".exe" if os.name == "nt" else ""


@dataclass(frozen=True, slots=True)
class FFmpegTools:
    """A verified ffmpeg/ffprobe pair."""

    ffmpeg: Path
    ffprobe: Path
    version: str
    source: str

    @property
    def has_ffprobe(self) -> bool:
        return self.ffprobe.is_file()


def _candidate_dirs(configured: str | None) -> list[tuple[Path, str]]:
    """Directories to search, paired with a label for diagnostics."""
    candidates: list[tuple[Path, str]] = []

    if configured:
        path = Path(configured)
        # Accept either the executable itself or the directory containing it.
        candidates.append((path.parent if path.suffix else path, "settings"))

    env_value = os.environ.get("FFMPEG_PATH")
    if env_value:
        path = Path(env_value)
        candidates.append((path.parent if path.suffix else path, "environment"))

    candidates.append((PATHS.bundled_ffmpeg_dir, "bundled"))

    on_path = shutil.which("ffmpeg")
    if on_path:
        candidates.append((Path(on_path).parent, "PATH"))

    return candidates


def find_ffmpeg(configured: str | None = None) -> FFmpegTools | None:
    """Locate a working ffmpeg. Returns ``None`` when nothing usable is found."""
    for directory, source in _candidate_dirs(configured):
        ffmpeg = directory / f"ffmpeg{_EXE}"
        if not ffmpeg.is_file():
            continue
        ok, version_line = probe_executable(ffmpeg, ["-version"], timeout=20)
        if not ok:
            logger.debug("ffmpeg at %s did not run: %s", ffmpeg, version_line)
            continue

        ffprobe = directory / f"ffprobe{_EXE}"
        if not ffprobe.is_file():
            fallback = shutil.which("ffprobe")
            ffprobe = Path(fallback) if fallback else ffprobe
            if not ffprobe.is_file():
                logger.warning("found ffmpeg at %s but no ffprobe beside it", ffmpeg)

        logger.info("using ffmpeg from %s (%s)", ffmpeg, source)
        return FFmpegTools(
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            version=version_line.strip(),
            source=source,
        )
    return None


def require_ffmpeg(configured: str | None = None) -> FFmpegTools:
    """Locate ffmpeg or raise a Persian-messaged dependency error."""
    tools = find_ffmpeg(configured)
    if tools is None:
        raise FFmpegNotFoundError(
            "no working ffmpeg found in settings, environment, bundle or PATH"
        )
    return tools


@lru_cache(maxsize=4)
def _cached(configured: str | None) -> FFmpegTools | None:
    return find_ffmpeg(configured)


def find_ffmpeg_cached(configured: str | None = None) -> FFmpegTools | None:
    """Cached variant for hot paths such as the dependency status endpoint."""
    return _cached(configured)


def clear_cache() -> None:
    """Called when the FFmpeg path setting changes."""
    _cached.cache_clear()

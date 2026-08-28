"""Claude CLI discovery.

Resolution order, first hit wins:

1. the path saved in Settings (``ai.claude_cli_path``) - the manual override
   the settings page exposes;
2. the ``CLAUDE_CLI_PATH`` environment variable;
3. ``claude`` on ``PATH`` via :func:`shutil.which`;
4. the well-known per-user install locations Claude Code uses on Windows.

Every result is verified by actually running ``--version``, because a stale
entry on ``PATH`` is common after an uninstall.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.process import probe_executable

logger = get_logger(__name__)

#: Locations Claude Code installs to on Windows, checked in order.
_WELL_KNOWN = (
    Path.home() / ".local" / "bin" / "claude.exe",
    Path.home() / "AppData" / "Local" / "Programs" / "claude" / "claude.exe",
    Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd",
)


@dataclass(frozen=True, slots=True)
class CliDetection:
    """Outcome of a discovery attempt."""

    found: bool
    path: Path | None = None
    version: str | None = None
    source: str = ""
    error: str = ""


def _verify(candidate: Path | str, source: str) -> CliDetection | None:
    """Run ``--version`` and return a detection if it succeeds."""
    path = Path(candidate)
    ok, output = probe_executable(path, ["--version"], timeout=30)
    if not ok:
        logger.debug("claude candidate %s from %s failed: %s", path, source, output)
        return None
    return CliDetection(found=True, path=path, version=output.strip(), source=source)


def detect_claude_cli(configured_path: str | None = None) -> CliDetection:
    """Locate a working Claude CLI. Never raises."""
    tried: list[str] = []

    if configured_path:
        tried.append(configured_path)
        candidate = Path(configured_path)
        if candidate.is_file():
            result = _verify(candidate, "settings")
            if result:
                return result
        else:
            logger.info("configured claude path does not exist: %s", configured_path)

    env_path = os.environ.get("CLAUDE_CLI_PATH")
    if env_path:
        tried.append(env_path)
        if Path(env_path).is_file():
            result = _verify(env_path, "environment")
            if result:
                return result

    which = shutil.which("claude")
    if which:
        tried.append(which)
        result = _verify(which, "PATH")
        if result:
            return result

    for candidate in _WELL_KNOWN:
        if candidate.is_file():
            tried.append(str(candidate))
            result = _verify(candidate, "well-known location")
            if result:
                return result

    return CliDetection(
        found=False,
        error=(
            "ابزار خط فرمان Claude پیدا نشد. "
            "مسیرهای بررسی‌شده: " + (", ".join(tried) if tried else "PATH")
        ),
    )

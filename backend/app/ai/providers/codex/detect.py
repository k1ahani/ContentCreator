"""OpenAI Codex CLI discovery and authentication status.

Mirrors ``app/ai/providers/claude/detect.py`` in shape, but Codex needs one
more check that Claude's detector does not: authentication is a *separate*
signal from "is the binary installed", and checking it is cheap enough to do
eagerly.

That second check exists because of a real, measured behaviour difference: an
unauthenticated ``codex exec`` call does not fail fast. It retries the
WebSocket transport five times, falls back to HTTPS, retries five more times,
and only then reports failure - roughly 35-40 seconds end to end on this
machine before it ever reaches ``turn.failed``. Reporting "unavailable" from a
call that slow would make the provider selector and the dependency dashboard
feel broken. ``codex login status`` is a local, instant check (no network
retry loop observed) that answers "would a real call succeed" without paying
that cost - use it, never a live ``exec`` call, for availability checks.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.process import ProcessSpec, probe_executable, run_process

logger = get_logger(__name__)

#: Locations the npm-distributed Codex CLI installs to on Windows, checked in
#: order after PATH. ``npm install -g @openai/codex`` places both of these in
#: the global npm prefix.
_WELL_KNOWN = (
    Path.home() / "AppData" / "Roaming" / "npm" / "codex.cmd",
    Path.home() / "AppData" / "Roaming" / "npm" / "codex",
)


@dataclass(frozen=True, slots=True)
class CliDetection:
    found: bool
    path: Path | None = None
    version: str | None = None
    source: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class AuthStatus:
    """Result of the (fast, local) ``codex login status`` check."""

    logged_in: bool
    detail: str = ""


def _verify(candidate: Path | str, source: str) -> CliDetection | None:
    path = Path(candidate)
    ok, output = probe_executable(path, ["--version"], timeout=20)
    if not ok:
        logger.debug("codex candidate %s from %s failed: %s", path, source, output)
        return None
    return CliDetection(found=True, path=path, version=output.strip(), source=source)


def detect_codex_cli(configured_path: str | None = None) -> CliDetection:
    """Locate a working Codex CLI. Never raises."""
    tried: list[str] = []

    if configured_path:
        tried.append(configured_path)
        candidate = Path(configured_path)
        if candidate.is_file():
            result = _verify(candidate, "settings")
            if result:
                return result
        else:
            logger.info("configured codex path does not exist: %s", configured_path)

    env_path = os.environ.get("CODEX_CLI_PATH")
    if env_path:
        tried.append(env_path)
        if Path(env_path).is_file():
            result = _verify(env_path, "environment")
            if result:
                return result

    which = shutil.which("codex")
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
            "ابزار خط فرمان Codex پیدا نشد. "
            "مسیرهای بررسی‌شده: " + (", ".join(tried) if tried else "PATH")
        ),
    )


def check_login_status(executable: Path, *, timeout: int = 15) -> AuthStatus:
    """Run ``codex login status`` - fast and local, never triggers a live API call.

    Verified behaviour (npm ``@openai/codex`` 0.150.1, no credentials
    configured): prints ``Not logged in`` and exits 1, in well under a
    second. A logged-in session is expected to exit 0 - this has not been
    verified against real credentials in this environment, so the check below
    treats *any* non-zero exit as "not logged in" rather than parsing output
    text, which is the more conservative and version-resilient reading.
    """
    try:
        result = run_process(
            ProcessSpec(argv=[str(executable), "login", "status"], timeout_seconds=timeout),
            check=False,
        )
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        logger.warning("codex login status could not be run: %s", exc)
        return AuthStatus(logged_in=False, detail=str(exc))

    output = (result.stdout or result.stderr).strip()
    if result.exit_code == 0:
        return AuthStatus(logged_in=True, detail=output)
    return AuthStatus(logged_in=False, detail=output or "Not logged in")

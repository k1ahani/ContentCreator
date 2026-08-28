"""Logging setup.

Two sinks:

* a rotating UTF-8 file in ``logs/app.log`` - full technical detail, this is
  where stack traces and raw process stderr go;
* the console - the same records, but the Windows console is not guaranteed to
  be UTF-8, so the stream handler is reconfigured explicitly. Without this,
  logging a Persian filename raises ``UnicodeEncodeError`` on cp1252 consoles.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from typing import Final

from app.core.paths import PATHS

_CONFIGURED = False

_FORMAT: Final = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DATEFMT: Final = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging. Safe to call more than once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    PATHS.logs_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    file_handler = logging.handlers.RotatingFileHandler(
        PATHS.logs_dir / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream = sys.stderr
    # Windows consoles default to a legacy code page; force UTF-8 so Persian
    # text and box-drawing characters in FFmpeg output do not crash the logger.
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    console_handler = logging.StreamHandler(stream)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # uvicorn installs its own noisy access logger; route it through ours.
    for noisy in ("uvicorn.access", "watchfiles.main", "httpx", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger. Prefer ``get_logger(__name__)``."""
    return logging.getLogger(name)

"""Bootstrap configuration.

This is deliberately *not* the same thing as user settings:

* **Bootstrap config** (this module) is what the process needs before it can
  talk to the database - host, port, log level, worker count. It comes from
  environment variables and ``config/app.json``, and changing it requires a
  restart.
* **User settings** (``app/services/settings.py``) live in SQLite, are edited
  from the Persian settings page, and take effect immediately.

Anything a user should be able to change from the UI belongs in user settings,
not here.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.paths import PATHS


class AppConfig(BaseSettings):
    """Process-level configuration. Environment variables win over the file."""

    model_config = SettingsConfigDict(
        env_prefix="CCA_",
        env_file=str(PATHS.config_dir / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- server ------------------------------------------------------------
    host: str = "127.0.0.1"
    #: Windows reserves blocks of TCP ports for Hyper-V/WinNAT, and binding
    #: inside one fails with WinError 10013 even though nothing is listening.
    #: Check with `netsh interface ipv4 show excludedportrange protocol=tcp`.
    #: 8420 sits outside the ranges observed on a normal Windows 11 install and
    #: away from the usual dev-server ports (3000/5173/8000/8080).
    port: int = 8420
    #: How many consecutive ports to try if the configured one is unusable.
    port_fallback_attempts: int = Field(default=20, ge=0, le=100)
    #: Vite dev server origin, allowed through CORS in development.
    frontend_dev_origin: str = "http://localhost:5173"
    #: When true the backend also serves the built frontend from frontend/dist.
    serve_frontend: bool = True

    # -- runtime -----------------------------------------------------------
    log_level: str = "INFO"
    #: Concurrent background job workers. Media work is CPU/IO heavy; 2 keeps
    #: the machine responsive while still allowing an AI call to overlap a render.
    job_workers: int = Field(default=2, ge=1, le=8)
    #: Hard ceiling for a single external process, in seconds.
    process_timeout_seconds: int = Field(default=3600, ge=30)
    #: Rows of stdout/stderr retained in memory per running job for live view.
    log_ring_size: int = Field(default=2000, ge=100)

    # -- storage -----------------------------------------------------------
    database_path: Path = Field(default_factory=lambda: PATHS.database_file)

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level: {value}")
        return level

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _file_overrides() -> dict[str, Any]:
    """Read ``config/app.json`` if present. Missing or malformed -> ignored."""
    config_file = PATHS.config_dir / "app.json"
    if not config_file.is_file():
        return {}
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Return the process-wide configuration singleton."""
    PATHS.ensure_base_dirs()
    return AppConfig(**_file_overrides())

"""Application services.

Services coordinate repositories, providers and the filesystem. They contain
the rules that are not specific to one job handler and not generic enough for
``core``.
"""

from app.services.settings import SettingsService

__all__ = ["SettingsService"]

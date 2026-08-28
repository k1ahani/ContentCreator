"""Repositories: the only place raw SQL for an entity is written.

Services compose repositories; API routers never touch SQL. Each repository
owns exactly one aggregate and is responsible for mapping ``sqlite3.Row`` to
the corresponding domain model.
"""

from app.db.repositories.assets import AssetRepository
from app.db.repositories.documents import DocumentRepository
from app.db.repositories.jobs import JobRepository
from app.db.repositories.projects import ProjectRepository
from app.db.repositories.prompts import PromptRepository
from app.db.repositories.settings import SettingsRepository
from app.db.repositories.subtitles import SubtitleRepository

__all__ = [
    "AssetRepository",
    "DocumentRepository",
    "JobRepository",
    "ProjectRepository",
    "PromptRepository",
    "SettingsRepository",
    "SubtitleRepository",
]

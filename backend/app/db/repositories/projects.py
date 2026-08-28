"""Project persistence."""

from __future__ import annotations

import sqlite3

from app.core.ids import new_id
from app.db.connection import utcnow
from app.db.repositories.base import BaseRepository
from app.domain.enums import ProjectStatus
from app.domain.project import Project, ProjectCreate, ProjectUpdate

_SELECT = """
SELECT p.*,
       (SELECT COUNT(*) FROM media_assets   a WHERE a.project_id = p.id) AS asset_count,
       (SELECT COUNT(*) FROM text_documents d WHERE d.project_id = p.id) AS document_count,
       (SELECT COUNT(*) FROM jobs           j WHERE j.project_id = p.id
                                             AND j.status IN ('queued', 'running')) AS active_job_count
FROM projects p
"""


class ProjectRepository(BaseRepository):
    def create(self, data: ProjectCreate) -> Project:
        now = utcnow()
        project_id = new_id()
        self.db.execute(
            """
            INSERT INTO projects (id, name, description, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, data.name.strip(), data.description.strip(),
             ProjectStatus.ACTIVE.value, now, now),
        )
        created = self.get(project_id)
        assert created is not None  # just inserted
        return created

    def get(self, project_id: str) -> Project | None:
        row = self.db.query_one(f"{_SELECT} WHERE p.id = ?", (project_id,))
        return self._map(row) if row else None

    def list(
        self,
        *,
        status: ProjectStatus | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Project]:
        clauses: list[str] = []
        params: list[object] = []
        if status:
            clauses.append("p.status = ?")
            params.append(status.value)
        if search:
            clauses.append("(p.name LIKE ? OR p.description LIKE ?)")
            needle = f"%{search}%"
            params.extend([needle, needle])

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        rows = self.db.query_all(
            f"{_SELECT}{where} ORDER BY p.updated_at DESC LIMIT ? OFFSET ?",
            tuple(params),
        )
        return [self._map(row) for row in rows]

    def count(self, *, status: ProjectStatus | None = None) -> int:
        if status:
            row = self.db.query_one(
                "SELECT COUNT(*) AS n FROM projects WHERE status = ?", (status.value,)
            )
        else:
            row = self.db.query_one("SELECT COUNT(*) AS n FROM projects")
        return int(row["n"]) if row else 0

    def update(self, project_id: str, data: ProjectUpdate) -> Project | None:
        fields: list[str] = []
        params: list[object] = []
        if data.name is not None:
            fields.append("name = ?")
            params.append(data.name.strip())
        if data.description is not None:
            fields.append("description = ?")
            params.append(data.description.strip())
        if data.status is not None:
            fields.append("status = ?")
            params.append(data.status.value)

        if fields:
            fields.append("updated_at = ?")
            params.extend([utcnow(), project_id])
            self.db.execute(
                f"UPDATE projects SET {', '.join(fields)} WHERE id = ?", tuple(params)
            )
        return self.get(project_id)

    def touch(self, project_id: str) -> None:
        """Bump ``updated_at``. Called whenever a child entity changes so the
        project list orders by real activity."""
        self.db.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?", (utcnow(), project_id)
        )

    def delete(self, project_id: str) -> bool:
        cursor = self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return cursor.rowcount > 0

    @staticmethod
    def _map(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            status=ProjectStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            asset_count=row["asset_count"],
            document_count=row["document_count"],
            active_job_count=row["active_job_count"],
        )

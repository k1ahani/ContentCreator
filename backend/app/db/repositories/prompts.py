"""Custom prompt persistence.

Version 1 exposes saved prompts and the built-in library. The table already
carries ``variables`` and ``category`` so template variables and prompt
categories can be added without a migration - see docs/EXTENDING_THE_APPLICATION.md.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core.ids import new_id
from app.db.connection import dumps, loads, utcnow
from app.db.repositories.base import BaseRepository
from app.domain.enums import AITaskType


class PromptRepository(BaseRepository):
    def create(
        self,
        *,
        name: str,
        body: str,
        task: AITaskType = AITaskType.GENERAL,
        category: str = "general",
        variables: list[str] | None = None,
        is_builtin: bool = False,
    ) -> dict[str, Any]:
        now = utcnow()
        prompt_id = new_id()
        self.db.execute(
            """
            INSERT INTO prompts
                (id, name, category, task, body, variables, is_builtin,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prompt_id,
                name,
                category,
                task.value,
                body,
                dumps(variables or []),
                1 if is_builtin else 0,
                now,
                now,
            ),
        )
        created = self.get(prompt_id)
        assert created is not None
        return created

    def get(self, prompt_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM prompts WHERE id = ?", (prompt_id,))
        return self._map(row) if row else None

    def list(self, *, task: AITaskType | None = None) -> list[dict[str, Any]]:
        if task:
            rows = self.db.query_all(
                "SELECT * FROM prompts WHERE task IN (?, 'general') ORDER BY name",
                (task.value,),
            )
        else:
            rows = self.db.query_all("SELECT * FROM prompts ORDER BY task, name")
        return [self._map(row) for row in rows]

    def update(
        self, prompt_id: str, *, name: str | None = None, body: str | None = None
    ) -> dict[str, Any] | None:
        fields: list[str] = []
        params: list[object] = []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if body is not None:
            fields.append("body = ?")
            params.append(body)
        if fields:
            fields.append("updated_at = ?")
            params.extend([utcnow(), prompt_id])
            assignments = ", ".join(fields)
            self.db.execute(
                f"UPDATE prompts SET {assignments} WHERE id = ?", tuple(params)
            )
        return self.get(prompt_id)

    def delete(self, prompt_id: str) -> bool:
        cursor = self.db.execute(
            "DELETE FROM prompts WHERE id = ? AND is_builtin = 0", (prompt_id,)
        )
        return cursor.rowcount > 0

    @staticmethod
    def _map(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "category": row["category"],
            "task": row["task"],
            "body": row["body"],
            "variables": loads(row["variables"], fallback=[]),
            "is_builtin": bool(row["is_builtin"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

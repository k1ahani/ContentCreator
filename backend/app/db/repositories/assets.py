"""Media asset persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.core.ids import new_id
from app.db.connection import dumps, loads, utcnow
from app.db.repositories.base import BaseRepository
from app.domain.asset import MediaAsset
from app.domain.enums import AssetType


class AssetRepository(BaseRepository):
    def create(
        self,
        *,
        project_id: str,
        type: AssetType,
        path: Path,
        original_filename: str,
        size_bytes: int = 0,
        format: str = "",
        duration_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MediaAsset:
        asset_id = new_id()
        self.db.execute(
            """
            INSERT INTO media_assets
                (id, project_id, type, original_filename, path, size_bytes,
                 format, duration_seconds, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                project_id,
                type.value,
                original_filename,
                str(path),
                size_bytes,
                format,
                duration_seconds,
                dumps(metadata or {}),
                utcnow(),
            ),
        )
        created = self.get(asset_id)
        assert created is not None
        return created

    def get(self, asset_id: str) -> MediaAsset | None:
        row = self.db.query_one("SELECT * FROM media_assets WHERE id = ?", (asset_id,))
        return self._map(row) if row else None

    def list_for_project(
        self, project_id: str, *, type: AssetType | None = None
    ) -> list[MediaAsset]:
        if type:
            rows = self.db.query_all(
                "SELECT * FROM media_assets WHERE project_id = ? AND type = ?"
                " ORDER BY created_at DESC",
                (project_id, type.value),
            )
        else:
            rows = self.db.query_all(
                "SELECT * FROM media_assets WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            )
        return [self._map(row) for row in rows]

    def latest(self, project_id: str, type: AssetType) -> MediaAsset | None:
        row = self.db.query_one(
            "SELECT * FROM media_assets WHERE project_id = ? AND type = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (project_id, type.value),
        )
        return self._map(row) if row else None

    def delete(self, asset_id: str) -> bool:
        cursor = self.db.execute("DELETE FROM media_assets WHERE id = ?", (asset_id,))
        return cursor.rowcount > 0

    @staticmethod
    def _map(row: sqlite3.Row) -> MediaAsset:
        return MediaAsset(
            id=row["id"],
            project_id=row["project_id"],
            type=AssetType(row["type"]),
            original_filename=row["original_filename"],
            path=row["path"],
            size_bytes=row["size_bytes"],
            format=row["format"],
            duration_seconds=row["duration_seconds"],
            metadata=loads(row["metadata"]),
            created_at=row["created_at"],
        )

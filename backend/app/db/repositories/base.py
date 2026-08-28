"""Shared repository plumbing."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.db.connection import Database


class BaseRepository:
    """Holds the database handle and a couple of mapping helpers.

    Deliberately thin: there is no generic active-record layer, because every
    entity here has a slightly different JSON-column shape and a generic mapper
    would obscure more than it saves.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    def _exists(self, table: str, entity_id: str) -> bool:
        row = self.db.query_one(f"SELECT 1 FROM {table} WHERE id = ?", (entity_id,))
        return row is not None

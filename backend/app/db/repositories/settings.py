"""Settings persistence.

A single key/value table with JSON values. Defaults are *not* stored here -
they live in ``app/services/settings.py`` so that adding a new setting never
requires a migration and an old database keeps working after an upgrade.
"""

from __future__ import annotations

from typing import Any

from app.db.connection import dumps, loads, utcnow
from app.db.repositories.base import BaseRepository

_MISSING = object()


class SettingsRepository(BaseRepository):
    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        if row is None:
            return default
        return loads(row["value"], fallback=default)

    def get_all(self) -> dict[str, Any]:
        rows = self.db.query_all("SELECT key, value FROM settings")
        return {row["key"]: loads(row["value"]) for row in rows}

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value,
                                            updated_at = excluded.updated_at
            """,
            (key, dumps(value), utcnow()),
        )

    def set_many(self, values: dict[str, Any]) -> None:
        if not values:
            return
        now = utcnow()
        self.db.connection.executemany(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value,
                                            updated_at = excluded.updated_at
            """,
            [(key, dumps(value), now) for key, value in values.items()],
        )

    def delete(self, key: str) -> bool:
        cursor = self.db.execute("DELETE FROM settings WHERE key = ?", (key,))
        return cursor.rowcount > 0

    def reset_all(self) -> int:
        cursor = self.db.execute("DELETE FROM settings")
        return cursor.rowcount

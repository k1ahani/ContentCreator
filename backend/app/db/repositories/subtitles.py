"""Subtitle track and cue persistence.

Cue ordering is maintained explicitly through the ``idx`` column rather than
implied by ``start_seconds``: during a drag the editor writes new times cue by
cue, and an implicit sort would make rows jump around mid-edit.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.core.ids import new_id
from app.db.connection import dumps, loads, utcnow
from app.db.repositories.base import BaseRepository
from app.domain.enums import Language
from app.domain.subtitle import (
    CueCreate,
    CueUpdate,
    SubtitleCue,
    SubtitleStyle,
    SubtitleTrack,
    TrackCreate,
)


class SubtitleRepository(BaseRepository):
    # -- tracks ------------------------------------------------------------

    def create_track(self, project_id: str, data: TrackCreate) -> SubtitleTrack:
        now = utcnow()
        track_id = new_id()
        style = data.style or SubtitleStyle()
        self.db.execute(
            """
            INSERT INTO subtitle_tracks
                (id, project_id, name, language, style, source_document_id,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track_id,
                project_id,
                data.name,
                data.language.value,
                dumps(style.model_dump(mode="json")),
                data.source_document_id,
                now,
                now,
            ),
        )
        created = self.get_track(track_id)
        assert created is not None
        return created

    def get_track(
        self, track_id: str, *, with_cues: bool = True
    ) -> SubtitleTrack | None:
        row = self.db.query_one(
            "SELECT * FROM subtitle_tracks WHERE id = ?", (track_id,)
        )
        if not row:
            return None
        track = self._map_track(row)
        if with_cues:
            track.cues = self.list_cues(track_id)
        return track

    def list_tracks(self, project_id: str) -> list[SubtitleTrack]:
        rows = self.db.query_all(
            "SELECT * FROM subtitle_tracks WHERE project_id = ?"
            " ORDER BY updated_at DESC",
            (project_id,),
        )
        return [self._map_track(row) for row in rows]

    def update_track(
        self,
        track_id: str,
        *,
        name: str | None = None,
        language: Language | None = None,
        style: SubtitleStyle | None = None,
    ) -> SubtitleTrack | None:
        fields: list[str] = []
        params: list[object] = []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if language is not None:
            fields.append("language = ?")
            params.append(language.value)
        if style is not None:
            fields.append("style = ?")
            params.append(dumps(style.model_dump(mode="json")))

        if fields:
            fields.append("updated_at = ?")
            params.extend([utcnow(), track_id])
            assignments = ", ".join(fields)
            self.db.execute(
                f"UPDATE subtitle_tracks SET {assignments} WHERE id = ?",
                tuple(params),
            )
        return self.get_track(track_id)

    def touch_track(self, track_id: str) -> None:
        self.db.execute(
            "UPDATE subtitle_tracks SET updated_at = ? WHERE id = ?",
            (utcnow(), track_id),
        )

    def delete_track(self, track_id: str) -> bool:
        cursor = self.db.execute("DELETE FROM subtitle_tracks WHERE id = ?", (track_id,))
        return cursor.rowcount > 0

    # -- cues --------------------------------------------------------------

    def list_cues(self, track_id: str) -> list[SubtitleCue]:
        rows = self.db.query_all(
            "SELECT * FROM subtitle_cues WHERE track_id = ? ORDER BY idx, start_seconds",
            (track_id,),
        )
        return [self._map_cue(row) for row in rows]

    def get_cue(self, cue_id: str) -> SubtitleCue | None:
        row = self.db.query_one("SELECT * FROM subtitle_cues WHERE id = ?", (cue_id,))
        return self._map_cue(row) if row else None

    def add_cue(self, track_id: str, data: CueCreate) -> SubtitleCue:
        index = data.index
        if index is None:
            row = self.db.query_one(
                "SELECT COALESCE(MAX(idx), -1) + 1 AS next_idx"
                " FROM subtitle_cues WHERE track_id = ?",
                (track_id,),
            )
            index = int(row["next_idx"]) if row else 0
        else:
            # Make room at the requested position.
            self.db.execute(
                "UPDATE subtitle_cues SET idx = idx + 1 WHERE track_id = ? AND idx >= ?",
                (track_id, index),
            )

        cue_id = new_id()
        self.db.execute(
            """
            INSERT INTO subtitle_cues
                (id, track_id, idx, start_seconds, end_seconds, text,
                 style_overrides, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cue_id, track_id, index, data.start, data.end, data.text, "{}", "{}"),
        )
        self.touch_track(track_id)
        created = self.get_cue(cue_id)
        assert created is not None
        return created

    def replace_cues(self, track_id: str, cues: list[CueCreate]) -> list[SubtitleCue]:
        """Atomically swap a track's entire cue list.

        Used by subtitle *generation*, which produces a fresh set from a
        transcript. Editing goes through the per-cue methods instead.
        """
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM subtitle_cues WHERE track_id = ?", (track_id,))
            conn.executemany(
                """
                INSERT INTO subtitle_cues
                    (id, track_id, idx, start_seconds, end_seconds, text,
                     style_overrides, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (new_id(), track_id, index, cue.start, cue.end, cue.text, "{}", "{}")
                    for index, cue in enumerate(cues)
                ],
            )
            conn.execute(
                "UPDATE subtitle_tracks SET updated_at = ? WHERE id = ?",
                (utcnow(), track_id),
            )
        return self.list_cues(track_id)

    def retime_cues(
        self, track_id: str, timings: dict[str, tuple[float, float]]
    ) -> list[SubtitleCue]:
        """Rewrite the timings of existing cues, atomically, in one pass.

        The counterpart to :meth:`replace_cues` for synchronisation: batch
        re-timing changes *when* every cue appears but must not touch what it
        says. Going through ``replace_cues`` would delete and recreate the
        rows, discarding cue ids (breaking the editor's current selection) and
        any per-cue style overrides the user had set - so this updates in
        place instead. One transaction, because a half-applied sync leaves the
        track with some cues on the old timeline and some on the new one.
        """
        if not timings:
            return self.list_cues(track_id)

        with self.db.transaction() as conn:
            conn.executemany(
                "UPDATE subtitle_cues SET start_seconds = ?, end_seconds = ?"
                " WHERE id = ? AND track_id = ?",
                [
                    (start, end, cue_id, track_id)
                    for cue_id, (start, end) in timings.items()
                ],
            )
            conn.execute(
                "UPDATE subtitle_tracks SET updated_at = ? WHERE id = ?",
                (utcnow(), track_id),
            )
        return self.list_cues(track_id)

    def update_cue(self, cue_id: str, data: CueUpdate) -> SubtitleCue | None:
        fields: list[str] = []
        params: list[object] = []
        if data.start is not None:
            fields.append("start_seconds = ?")
            params.append(data.start)
        if data.end is not None:
            fields.append("end_seconds = ?")
            params.append(data.end)
        if data.text is not None:
            fields.append("text = ?")
            params.append(data.text)
        if data.style_overrides is not None:
            fields.append("style_overrides = ?")
            params.append(dumps(data.style_overrides))

        if not fields:
            return self.get_cue(cue_id)

        params.append(cue_id)
        assignments = ", ".join(fields)
        self.db.execute(
            f"UPDATE subtitle_cues SET {assignments} WHERE id = ?", tuple(params)
        )
        cue = self.get_cue(cue_id)
        if cue:
            self.touch_track(cue.track_id)
        return cue

    def delete_cue(self, cue_id: str) -> bool:
        cue = self.get_cue(cue_id)
        if not cue:
            return False
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM subtitle_cues WHERE id = ?", (cue_id,))
            conn.execute(
                "UPDATE subtitle_cues SET idx = idx - 1 WHERE track_id = ? AND idx > ?",
                (cue.track_id, cue.index),
            )
            conn.execute(
                "UPDATE subtitle_tracks SET updated_at = ? WHERE id = ?",
                (utcnow(), cue.track_id),
            )
        return True

    def reindex(self, track_id: str) -> None:
        """Renumber cues 0..n-1 in time order. Called after split/merge."""
        rows = self.db.query_all(
            "SELECT id FROM subtitle_cues WHERE track_id = ? ORDER BY start_seconds, idx",
            (track_id,),
        )
        with self.db.transaction() as conn:
            conn.executemany(
                "UPDATE subtitle_cues SET idx = ? WHERE id = ?",
                [(index, row["id"]) for index, row in enumerate(rows)],
            )

    # -- mapping -----------------------------------------------------------

    @staticmethod
    def _map_track(row: sqlite3.Row) -> SubtitleTrack:
        style_data: dict[str, Any] = loads(row["style"])
        return SubtitleTrack(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"],
            language=Language(row["language"]),
            style=SubtitleStyle(**style_data) if style_data else SubtitleStyle(),
            source_document_id=row["source_document_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            cues=[],
        )

    @staticmethod
    def _map_cue(row: sqlite3.Row) -> SubtitleCue:
        return SubtitleCue(
            id=row["id"],
            track_id=row["track_id"],
            index=row["idx"],
            start=row["start_seconds"],
            end=row["end_seconds"],
            text=row["text"],
            style_overrides=loads(row["style_overrides"]),
            metadata=loads(row["metadata"]),
        )

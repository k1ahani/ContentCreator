"""Text document persistence."""

from __future__ import annotations

import sqlite3

from app.core.ids import new_id
from app.db.connection import utcnow
from app.db.repositories.base import BaseRepository
from app.domain.document import DocumentCreate, DocumentUpdate, TextDocument
from app.domain.enums import DocumentType, Language


class DocumentRepository(BaseRepository):
    def create(self, project_id: str, data: DocumentCreate) -> TextDocument:
        now = utcnow()
        document_id = new_id()

        # A document derived from another continues its version sequence, which
        # is what lets the UI show "نسخه ۳" without a separate history table.
        version = 1
        if data.source_document_id:
            row = self.db.query_one(
                "SELECT version FROM text_documents WHERE id = ?",
                (data.source_document_id,),
            )
            if row:
                version = int(row["version"]) + 1

        self.db.execute(
            """
            INSERT INTO text_documents
                (id, project_id, type, title, content, language, version,
                 source_document_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                project_id,
                data.type.value,
                data.title,
                data.content,
                data.language.value,
                version,
                data.source_document_id,
                now,
                now,
            ),
        )
        created = self.get(document_id)
        assert created is not None
        return created

    def get(self, document_id: str) -> TextDocument | None:
        row = self.db.query_one(
            "SELECT * FROM text_documents WHERE id = ?", (document_id,)
        )
        return self._map(row) if row else None

    def list_for_project(
        self, project_id: str, *, type: DocumentType | None = None
    ) -> list[TextDocument]:
        if type:
            rows = self.db.query_all(
                "SELECT * FROM text_documents WHERE project_id = ? AND type = ?"
                " ORDER BY updated_at DESC",
                (project_id, type.value),
            )
        else:
            rows = self.db.query_all(
                "SELECT * FROM text_documents WHERE project_id = ?"
                " ORDER BY updated_at DESC",
                (project_id,),
            )
        return [self._map(row) for row in rows]

    def latest(self, project_id: str, type: DocumentType) -> TextDocument | None:
        row = self.db.query_one(
            "SELECT * FROM text_documents WHERE project_id = ? AND type = ?"
            " ORDER BY updated_at DESC LIMIT 1",
            (project_id, type.value),
        )
        return self._map(row) if row else None

    def update(self, document_id: str, data: DocumentUpdate) -> TextDocument | None:
        fields: list[str] = []
        params: list[object] = []
        if data.title is not None:
            fields.append("title = ?")
            params.append(data.title)
        if data.content is not None:
            fields.append("content = ?")
            params.append(data.content)
        if data.language is not None:
            fields.append("language = ?")
            params.append(data.language.value)

        if fields:
            fields.append("updated_at = ?")
            params.extend([utcnow(), document_id])
            self.db.execute(
                f"UPDATE text_documents SET {', '.join(fields)} WHERE id = ?",
                tuple(params),
            )
        return self.get(document_id)

    def delete(self, document_id: str) -> bool:
        cursor = self.db.execute(
            "DELETE FROM text_documents WHERE id = ?", (document_id,)
        )
        return cursor.rowcount > 0

    @staticmethod
    def _map(row: sqlite3.Row) -> TextDocument:
        return TextDocument(
            id=row["id"],
            project_id=row["project_id"],
            type=DocumentType(row["type"]),
            title=row["title"],
            content=row["content"],
            language=Language(row["language"]),
            version=row["version"],
            source_document_id=row["source_document_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

"""Text document entity.

Documents are versioned by *creation*, not by mutation: an AI pass never
overwrites its input, it writes a new row that points back to its source. That
is what makes the "original / AI result / apply or reject" workflow in the text
editor honest rather than cosmetic.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import DocumentType, Language


class TextDocument(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    type: DocumentType
    title: str = ""
    content: str = ""
    language: Language = Language.PERSIAN
    version: int = 1
    #: Document this one was derived from, if any.
    source_document_id: str | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def character_count(self) -> int:
        return len(self.content)

    @property
    def word_count(self) -> int:
        return len(self.content.split())


class DocumentCreate(BaseModel):
    type: DocumentType
    title: str = Field(default="", max_length=200)
    content: str = ""
    language: Language = Language.PERSIAN
    source_document_id: str | None = None


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = None
    language: Language | None = None

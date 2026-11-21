from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    knowledge_base_id: UUID
    title: str = Field(
        min_length=1,
        max_length=200,
    )
    content: str = ""
    source_document_id: UUID | None = None
    metadata: dict = Field(
        default_factory=dict,
    )


class NoteUpdate(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )
    content: str | None = None
    source_document_id: UUID | None = None
    metadata: dict | None = None


class NoteResponse(BaseModel):
    id: UUID
    user_id: UUID
    knowledge_base_id: UUID | None
    source_document_id: UUID | None
    title: str
    content: str
    vector_index_status: str
    vector_index_error: str | None
    metadata: dict
    created_at: datetime
    updated_at: datetime

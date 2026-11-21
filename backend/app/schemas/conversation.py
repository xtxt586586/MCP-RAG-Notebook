from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    citations: list
    metadata: dict
    created_at: datetime


class ConversationResponse(BaseModel):
    id: UUID
    knowledge_base_id: UUID | None
    title: str
    model_name: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    archived_at: datetime | None


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    archived: bool | None = None


class ConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: list[MessageResponse]

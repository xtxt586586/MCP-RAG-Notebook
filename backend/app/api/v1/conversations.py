from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.models import Conversation, Message
from app.schemas.conversation import ConversationUpdateRequest


router = APIRouter(prefix="/conversations", tags=["会话管理"])


def serialize_conversation(
    conversation: Conversation,
    message_count: int,
) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "knowledge_base_id": conversation.knowledge_base_id,
        "title": conversation.title,
        "model_name": conversation.model_name,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "message_count": message_count,
        "archived_at": conversation.archived_at,
    }


async def get_owned_conversation(
    *,
    conversation_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession,
) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在或不属于当前用户",
        )
    return conversation


@router.get("")
async def list_conversations(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    knowledge_base_id: UUID | None = Query(default=None),
    query: str | None = Query(default=None, max_length=2000),
    limit: int = Query(default=50, ge=1, le=100),
    include_archived: bool = Query(default=False),
) -> dict[str, Any]:
    count_subquery = (
        select(
            Message.conversation_id,
            func.count(Message.id).label("message_count"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    statement = (
        select(
            Conversation,
            func.coalesce(count_subquery.c.message_count, 0),
        )
        .outerjoin(
            count_subquery,
            count_subquery.c.conversation_id == Conversation.id,
        )
        .where(Conversation.user_id == current_user.id)
        .where(func.coalesce(count_subquery.c.message_count, 0) > 0)
    )

    if not include_archived:
        statement = statement.where(Conversation.archived_at.is_(None))

    if knowledge_base_id is not None:
        statement = statement.where(
            Conversation.knowledge_base_id == knowledge_base_id
        )

    normalized_query = (query or "").strip()
    if normalized_query:
        statement = statement.where(
            Conversation.title.ilike(f"%{normalized_query}%")
        )

    statement = statement.order_by(
        Conversation.updated_at.desc(),
        Conversation.created_at.desc(),
    ).limit(limit)

    result = await db.execute(statement)
    items = [
        serialize_conversation(conversation, int(message_count))
        for conversation, message_count in result.all()
    ]
    return {"items": items, "count": len(items)}


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: UUID,
    request: ConversationUpdateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conversation = await get_owned_conversation(
        conversation_id=conversation_id,
        current_user=current_user,
        db=db,
    )

    if request.title is not None:
        title = request.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="会话标题不能为空")
        conversation.title = title

    if request.archived is not None:
        conversation.archived_at = (
            datetime.now(timezone.utc)
            if request.archived
            else None
        )

    await db.commit()
    await db.refresh(conversation)
    message_count_result = await db.execute(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation.id,
        )
    )
    return serialize_conversation(
        conversation,
        int(message_count_result.scalar_one()),
    )


@router.get("/{conversation_id}/memory")
async def get_conversation_memory(
    conversation_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conversation = await get_owned_conversation(
        conversation_id=conversation_id,
        current_user=current_user,
        db=db,
    )
    max_turns = current_user.agent_history_max_turns
    if max_turns is None:
        max_turns = settings.agent_history_max_turns
    max_turns = max(0, min(max_turns, 20))
    message_statement = select(Message).where(
        Message.conversation_id == conversation.id,
    )
    if conversation.memory_reset_at is not None:
        message_statement = message_statement.where(
            Message.created_at > conversation.memory_reset_at,
        )
    result = await db.execute(
        message_statement
        .order_by(
            Message.created_at.desc(),
            case((Message.role == "assistant", 0), else_=1),
            Message.id.desc(),
        )
        .limit(max_turns * 2),
    )
    messages = list(reversed(result.scalars().all()))
    return {
        "conversation_id": str(conversation.id),
        "max_turns": max_turns,
        "history_turns": len(messages) // 2,
        "memory_summary": conversation.memory_summary,
        "memory_reset_at": conversation.memory_reset_at,
        "messages": [
            {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "role": message.role,
                "content": message.content,
                "citations": message.citations or [],
                "metadata": message.extra_metadata or {},
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }


@router.delete("/{conversation_id}/memory")
async def clear_conversation_memory(
    conversation_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    conversation = await get_owned_conversation(
        conversation_id=conversation_id,
        current_user=current_user,
        db=db,
    )
    conversation.memory_summary = None
    conversation.memory_summary_turns = 0
    conversation.memory_reset_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "cleared_messages": 0,
        "memory_reset": True,
        "memory_reset_at": conversation.memory_reset_at,
    }


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conversation = await get_owned_conversation(
        conversation_id=conversation_id,
        current_user=current_user,
        db=db,
    )
    count_result = await db.execute(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation.id
        )
    )
    message_count = int(count_result.scalar_one())
    messages_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(
            Message.created_at.asc(),
            case((Message.role == "user", 0), else_=1),
            Message.id.asc(),
        )
    )
    messages = messages_result.scalars().all()
    return {
        "conversation": serialize_conversation(
            conversation, message_count
        ),
        "messages": [
            {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "role": message.role,
                "content": message.content,
                "citations": message.citations or [],
                "metadata": message.extra_metadata or {},
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    conversation = await get_owned_conversation(
        conversation_id=conversation_id,
        current_user=current_user,
        db=db,
    )
    await db.delete(conversation)
    await db.commit()

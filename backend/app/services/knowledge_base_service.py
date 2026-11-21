"""Resolve the single logical knowledge base owned by a user.

The database keeps a knowledge-base row because documents, vectors, notes and
conversations use its UUID as their internal partition key. The application
surface exposes one logical knowledge base per user.
"""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeBase


DEFAULT_KNOWLEDGE_BASE_NAME = "我的知识库"
DEFAULT_KNOWLEDGE_BASE_DESCRIPTION = "当前账户的个人知识库"


async def get_or_create_user_knowledge_base(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> KnowledgeBase:
    """Return the user's only knowledge base, creating it on first use."""
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.user_id == user_id)
        .order_by(KnowledgeBase.created_at.asc(), KnowledgeBase.id.asc())
        .limit(1)
    )
    knowledge_base = result.scalar_one_or_none()
    if knowledge_base is not None:
        return knowledge_base

    knowledge_base = KnowledgeBase(
        user_id=user_id,
        name=DEFAULT_KNOWLEDGE_BASE_NAME,
        description=DEFAULT_KNOWLEDGE_BASE_DESCRIPTION,
    )
    db.add(knowledge_base)
    try:
        await db.flush()
    except IntegrityError:
        # A concurrent first request may have created the row. Reuse it.
        await db.rollback()
        result = await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.user_id == user_id)
            .order_by(KnowledgeBase.created_at.asc(), KnowledgeBase.id.asc())
            .limit(1)
        )
        knowledge_base = result.scalar_one_or_none()
        if knowledge_base is None:
            raise

    return knowledge_base


async def get_current_user_knowledge_base(
    *,
    db: AsyncSession,
    user_id: UUID,
    requested_id: UUID | None = None,
) -> KnowledgeBase:
    """Resolve the canonical row and reject a stale/non-owner ID."""
    knowledge_base = await get_or_create_user_knowledge_base(
        db=db,
        user_id=user_id,
    )
    # A few lightweight service tests return the UUID directly instead of an
    # ORM instance; accepting both keeps the resolver boundary simple.
    canonical_id = getattr(knowledge_base, "id", knowledge_base)
    if requested_id is not None and requested_id != canonical_id:
        raise HTTPException(
            status_code=404,
            detail="知识库不存在或不属于当前用户",
        )
    return knowledge_base

# 知识库 CRUD 模块
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.core.database import get_db
from app.models import KnowledgeBase
from app.schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from app.services.knowledge_base_service import (
    get_current_user_knowledge_base,
    get_or_create_user_knowledge_base,
)


router = APIRouter(
    prefix="/knowledge-bases",
    tags=["知识库"],
)


@router.post(
    "",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_base(
    request: KnowledgeBaseCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    # Kept for backward compatibility. It now updates the user's singleton
    # instead of creating a second selectable knowledge base.
    knowledge_base = await get_or_create_user_knowledge_base(
        db=db,
        user_id=current_user.id,
    )
    knowledge_base.name = request.name
    if request.description is not None:
        knowledge_base.description = request.description
    await db.commit()
    await db.refresh(knowledge_base)

    return KnowledgeBaseResponse.model_validate(
        knowledge_base
    )


@router.get(
    "",
    response_model=list[KnowledgeBaseResponse],
)
async def list_knowledge_bases(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[KnowledgeBaseResponse]:
    knowledge_base = await get_or_create_user_knowledge_base(
        db=db,
        user_id=current_user.id,
    )
    await db.commit()

    return [
        KnowledgeBaseResponse.model_validate(knowledge_base)
    ]


@router.get(
    "/current",
    response_model=KnowledgeBaseResponse,
)
async def get_current_knowledge_base(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    """Return the only knowledge base for the current user."""
    knowledge_base = await get_or_create_user_knowledge_base(
        db=db,
        user_id=current_user.id,
    )
    await db.commit()
    return KnowledgeBaseResponse.model_validate(knowledge_base)


@router.get(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
)
async def get_knowledge_base(
    knowledge_base_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    knowledge_base = await get_current_user_knowledge_base(
        db=db,
        user_id=current_user.id,
        requested_id=knowledge_base_id,
    )

    return KnowledgeBaseResponse.model_validate(
        knowledge_base
    )


@router.patch(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
)
async def update_knowledge_base(
    knowledge_base_id: UUID,
    request: KnowledgeBaseUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    knowledge_base = await get_current_user_knowledge_base(
        db=db,
        user_id=current_user.id,
        requested_id=knowledge_base_id,
    )

    update_data = request.model_dump(
        exclude_unset=True
    )

    for field_name, value in update_data.items():
        setattr(
            knowledge_base,
            field_name,
            value,
        )

    await db.commit()
    await db.refresh(knowledge_base)

    return KnowledgeBaseResponse.model_validate(
        knowledge_base
    )


@router.delete(
    "/{knowledge_base_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_knowledge_base(
    knowledge_base_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await get_current_user_knowledge_base(
        db=db,
        user_id=current_user.id,
        requested_id=knowledge_base_id,
    )
    raise HTTPException(
        status_code=409,
        detail="个人知识库不能删除；请删除其中的文档或笔记",
    )

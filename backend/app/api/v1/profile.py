from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.models import User
from app.schemas import (
    AgentMemorySettingsRequest,
    AgentMemorySettingsResponse,
    PasswordChangeRequest,
    ProfileUpdateRequest,
    UserResponse,
)


router = APIRouter(prefix="/profile", tags=["个人信息"])


def memory_settings_response(user: User) -> AgentMemorySettingsResponse:
    return AgentMemorySettingsResponse(
        max_turns=(
            settings.agent_history_max_turns
            if user.agent_history_max_turns is None
            else user.agent_history_max_turns
        ),
        default_max_turns=settings.agent_history_max_turns,
    )


@router.get("", response_model=UserResponse)
async def get_profile(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.get("/agent-memory", response_model=AgentMemorySettingsResponse)
async def get_agent_memory_settings(
    current_user: CurrentUser,
) -> AgentMemorySettingsResponse:
    return memory_settings_response(current_user)


@router.put("/agent-memory", response_model=AgentMemorySettingsResponse)
async def update_agent_memory_settings(
    request: AgentMemorySettingsRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> AgentMemorySettingsResponse:
    current_user.agent_history_max_turns = request.max_turns
    await db.commit()
    await db.refresh(current_user)
    return memory_settings_response(current_user)


@router.put("", response_model=UserResponse)
async def update_profile(
    request: ProfileUpdateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value.strip() if isinstance(value, str) else value)

    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.post("/password", response_model=UserResponse)
async def change_password(
    request: PasswordChangeRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    if not verify_password(request.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前密码不正确",
        )

    current_user.password_hash = hash_password(request.new_password)
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)

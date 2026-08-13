import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import KnowledgeBase
from app.services.agent.mcp_agent_service import (
    mcp_agent_service,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agent",
    tags=["MCP Agent"],
)


class AgentChatRequest(BaseModel):
    user_id: UUID
    knowledge_base_id: UUID
    question: str = Field(
        min_length=1,
        max_length=3000,
    )

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("问题不能为空")

        return value


class AgentToolStep(BaseModel):
    step: int
    server_name: str
    tool_name: str
    arguments: dict[str, Any]
    is_error: bool
    result_preview: str


class AgentChatResponse(BaseModel):
    query: str
    answer: str
    tool_steps: list[AgentToolStep]
    max_steps_reached: bool


@router.post(
    "/chat",
    response_model=AgentChatResponse,
)
async def agent_chat(
    request: AgentChatRequest,
    db: AsyncSession = Depends(get_db),
) -> AgentChatResponse:
    result = await db.execute(
        select(KnowledgeBase.id).where(
            KnowledgeBase.id
            == request.knowledge_base_id,
            KnowledgeBase.user_id
            == request.user_id,
        )
    )

    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=404,
            detail="知识库不存在或不属于当前用户",
        )

    try:
        agent_result = (
            await mcp_agent_service.answer(
                user_id=str(request.user_id),
                knowledge_base_id=str(
                    request.knowledge_base_id
                ),
                question=request.question,
            )
        )

        return AgentChatResponse(**agent_result)

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        logger.exception(
            "MCP Agent 外部服务调用失败"
        )

        raise HTTPException(
            status_code=502,
            detail="MCP Agent 外部服务调用失败",
        ) from exc

    except Exception as exc:
        logger.exception(
            "MCP Agent 处理失败"
        )

        raise HTTPException(
            status_code=500,
            detail="MCP Agent 处理失败",
        ) from exc
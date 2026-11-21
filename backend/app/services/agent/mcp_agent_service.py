from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.langchain_agent_service import (
    langchain_agent_service,
)


class MCPAgentService:
    async def answer(
            self,
            *,
            db: AsyncSession,
            user_id: str,
            knowledge_base_id: str,
            question: str,
            conversation_id: str | None = None,
            access_token: str | None = None,
    ) -> dict[str,Any]:
        return await langchain_agent_service.answer(
            db=db,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            question=question,
            conversation_id=conversation_id,
            access_token=access_token,
        )

    def stream_answer(
        self,
        *,
        db: AsyncSession,
        user_id: str,
        knowledge_base_id: str,
        question: str,
        conversation_id: str | None = None,
        access_token: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        return langchain_agent_service.stream_answer(
            db=db,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            question=question,
            conversation_id=conversation_id,
            access_token=access_token,
        )


mcp_agent_service = MCPAgentService()

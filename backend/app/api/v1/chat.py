import logging
from typing import Any
from uuid import UUID

import json
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

from app.services.llm.deepseek_service import (
    deepseek_service,
)

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import KnowledgeBase
from app.services.rag.rag_service import rag_service


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["RAG 问答"],
)


class ChatRequest(BaseModel):
    user_id: UUID
    knowledge_base_id: UUID

    question: str = Field(
        min_length=1,
        max_length=2000,
    )

    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
    )

    @field_validator("question")
    @classmethod
    def validate_question(
        cls,
        value: str,
    ) -> str:
        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError("问题不能为空")

        return normalized_value


class CitationSource(BaseModel):
    citation: str
    document_id: str
    chunk_id: str
    chunk_index: int
    file_name: str
    page_number: int | None = None
    score: float
    excerpt: str


class ChatResponse(BaseModel):
    query: str
    answer: str
    retrieval_mode: str
    sources: list[CitationSource]


@router.post(
    "",
    response_model=ChatResponse,
)
async def chat_with_knowledge_base(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    knowledge_base_result = await db.execute(
        select(KnowledgeBase.id).where(
            KnowledgeBase.id
            == request.knowledge_base_id,
            KnowledgeBase.user_id
            == request.user_id,
        )
    )

    knowledge_base_id = (
        knowledge_base_result.scalar_one_or_none()
    )

    if knowledge_base_id is None:
        raise HTTPException(
            status_code=404,
            detail="知识库不存在或不属于当前用户",
        )

    try:
        result: dict[str, Any] = (
            await rag_service.answer(
                user_id=str(request.user_id),
                knowledge_base_id=str(
                    request.knowledge_base_id
                ),
                query=request.question,
                top_k=request.top_k,
            )
        )

        return ChatResponse(**result)

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        logger.exception(
            "DeepSeek 服务调用失败"
        )

        raise HTTPException(
            status_code=502,
            detail="大模型服务请求失败",
        ) from exc

    except Exception as exc:
        logger.exception(
            "RAG 问答处理失败"
        )

        raise HTTPException(
            status_code=500,
            detail="RAG 问答处理失败",
        ) from exc


def format_sse_event(
    *,
    event: str,
    data: dict[str, Any],
) -> str:
    json_data = json.dumps(
        data,
        ensure_ascii=False,
    )

    return (
        f"event: {event}\n"
        f"data: {json_data}\n\n"
    )


@router.post("/stream")
async def stream_chat_with_knowledge_base(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    knowledge_base_result = await db.execute(
        select(KnowledgeBase.id).where(
            KnowledgeBase.id
            == request.knowledge_base_id,
            KnowledgeBase.user_id
            == request.user_id,
        )
    )

    knowledge_base_id = (
        knowledge_base_result.scalar_one_or_none()
    )

    if knowledge_base_id is None:
        raise HTTPException(
            status_code=404,
            detail="知识库不存在或不属于当前用户",
        )

    try:
        prepared = (
            await rag_service.prepare_streaming_answer(
                user_id=str(request.user_id),
                knowledge_base_id=str(
                    request.knowledge_base_id
                ),
                query=request.question,
                top_k=request.top_k,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "流式 RAG 检索准备失败"
        )

        raise HTTPException(
            status_code=500,
            detail="RAG 检索准备失败",
        ) from exc

    async def event_generator() -> AsyncIterator[str]:
        yield format_sse_event(
            event="sources",
            data={
                "query": prepared["query"],
                "sources": prepared["sources"],
            },
        )

        fallback_answer = prepared.get(
            "fallback_answer"
        )

        if fallback_answer:
            yield format_sse_event(
                event="token",
                data={
                    "content": fallback_answer,
                },
            )

            yield format_sse_event(
                event="done",
                data={
                    "status": "completed",
                },
            )

            return

        try:
            async for token in (
                deepseek_service.stream_generate(
                    messages=prepared["messages"],
                    temperature=0.1,
                )
            ):
                yield format_sse_event(
                    event="token",
                    data={
                        "content": token,
                    },
                )

            yield format_sse_event(
                event="done",
                data={
                    "status": "completed",
                },
            )

        except Exception:
            logger.exception(
                "DeepSeek 流式回答失败"
            )

            yield format_sse_event(
                event="error",
                data={
                    "message": (
                        "大模型流式回答失败"
                    ),
                },
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
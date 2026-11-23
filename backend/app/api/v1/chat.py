import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from fastapi.responses import StreamingResponse
from pydantic import (
    BaseModel,
    Field,
    field_validator,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    Conversation,
    KnowledgeBase,
    Message,
)
from app.services.llm.deepseek_service import (
    deepseek_service,
)
from app.services.rag.rag_service import (
    rag_service,
)
from app.services.knowledge_base_service import (
    get_current_user_knowledge_base,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["RAG 问答"],
)

class ChatRequest(BaseModel):
    knowledge_base_id: UUID

    require_sources: bool = False

    conversation_id: UUID | None = None

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
    document_id: str | None = None
    chunk_id: str | None = None
    chunk_index: int | None = None
    file_name: str | None = None
    page_number: int | None = None
    score: float | None = None
    excerpt: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    title: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    query: str
    retrieval_query: str
    answer: str
    retrieval_mode: str
    sources: list[CitationSource]


def build_general_messages(
    question: str,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是一个专业、准确、简洁的 AI 助手。"
                "当前问题未达到知识库相似度阈值，不要引用或假设任何知识库资料。"
                "如果问题需要实时信息，请明确说明限制。"
            ),
        },
        {
            "role": "user",
            "content": question,
        },
    ]


async def ensure_owned_knowledge_base(
    *,
    db: AsyncSession,
    knowledge_base_id: UUID,
    user_id: UUID,
) -> None:
    await get_current_user_knowledge_base(
        db=db,
        user_id=user_id,
        requested_id=knowledge_base_id,
    )


async def get_or_create_conversation(
    *,
    db: AsyncSession,
    current_user: CurrentUser,
    knowledge_base_id: UUID,
    conversation_id: UUID | None,
    question: str,
) -> Conversation:
    if conversation_id is not None:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id
                == conversation_id,
                Conversation.user_id
                == current_user.id,
                Conversation.knowledge_base_id
                == knowledge_base_id,
            )
        )

        conversation = (
            result.scalar_one_or_none()
        )

        if conversation is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "对话不存在或不属于"
                    "当前用户"
                ),
            )

        return conversation

    conversation = Conversation(
        user_id=current_user.id,
        knowledge_base_id=knowledge_base_id,
        title=question[:200],
        model_name=settings.deepseek_model,
    )

    db.add(conversation)
    await db.flush()

    return conversation


async def save_message(
    *,
    db: AsyncSession,
    conversation: Conversation,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    message = Message(
        conversation_id=conversation.id,
        role=role,
        content=content,
        citations=citations or [],
        extra_metadata=metadata or {},
    )

    db.add(message)

    conversation.updated_at = datetime.now(
        timezone.utc
    )

    await db.commit()


# ✨ 修改 save_message_pair 增加 retrieval_mode 参数
async def save_message_pair(
    *,
    db: AsyncSession,
    conversation: Conversation,
    question: str,
    answer: str,
    retrieval_query: str,
    sources: list[dict[str, Any]],
    retrieval_mode: str = "hybrid",
    metadata_extra: dict[str, Any] | None = None,
) -> None:
    base_metadata = {
        "retrieval_query": retrieval_query,
        "retrieval_mode": retrieval_mode,
    }

    # Tool execution details describe the assistant turn. Keeping them off
    # the user message prevents the UI from rendering tool activity below the
    # user's own prompt when a conversation is restored.
    assistant_metadata = {
        **base_metadata,
        **(metadata_extra or {}),
    }

    message_timestamp = datetime.now(timezone.utc)
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=question,
        citations=[],
        extra_metadata=base_metadata,
        created_at=message_timestamp,
    )

    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        citations=sources,
        extra_metadata=assistant_metadata,
        created_at=message_timestamp + timedelta(microseconds=1),
    )

    db.add(user_message)
    db.add(assistant_message)

    conversation.updated_at = datetime.now(
        timezone.utc
    )

    await db.commit()


@router.post(
    "",
    response_model=ChatResponse,
)
async def chat_with_knowledge_base(
    request: ChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    await ensure_owned_knowledge_base(
        db=db,
        knowledge_base_id=(
            request.knowledge_base_id
        ),
        user_id=current_user.id,
    )

    try:
        conversation = (
            await get_or_create_conversation(
                db=db,
                current_user=current_user,
                knowledge_base_id=(
                    request.knowledge_base_id
                ),
                conversation_id=(
                    request.conversation_id
                ),
                question=request.question,
            )
        )

        result = await rag_service.answer(
            db=db,
            user_id=str(current_user.id),
            knowledge_base_id=str(request.knowledge_base_id),
            query=request.question,
            top_k=request.top_k,
        )

        if request.require_sources and result.get("retrieval_mode") == "unavailable":
            raise HTTPException(status_code=503, detail="知识库检索暂不可用，请稍后重试")

        # The top-1 relevance threshold is the only routing decision.  A
        # low-score query falls back to a normal answer without RAG context.
        if not result["sources"] and not request.require_sources:
            result = {
                "query": request.question,
                "retrieval_query": result.get(
                    "retrieval_query",
                    request.question,
                ),
                "answer": await deepseek_service.generate(
                    messages=build_general_messages(request.question),
                    temperature=0.2,
                ),
                "retrieval_mode": "general",
                "sources": [],
                "route_score": result.get("route_score", 0.0),
            }

        # ✨ 保存消息时传入 retrieval_mode
        await save_message_pair(
            db=db,
            conversation=conversation,
            question=result["query"],
            answer=result["answer"],
            retrieval_query=result["retrieval_query"],
            sources=result["sources"],
            retrieval_mode=result["retrieval_mode"],
        )

        result["conversation_id"] = str(
            conversation.id
        )

        return ChatResponse(**result)

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        logger.exception(
            "DeepSeek 服务调用失败："
            "user_id=%s knowledge_base_id=%s",
            current_user.id,
            request.knowledge_base_id,
        )

        raise HTTPException(
            status_code=502,
            detail="大模型服务请求失败",
        ) from exc

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "RAG 问答处理失败："
            "user_id=%s knowledge_base_id=%s",
            current_user.id,
            request.knowledge_base_id,
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
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await ensure_owned_knowledge_base(
        db=db,
        knowledge_base_id=(
            request.knowledge_base_id
        ),
        user_id=current_user.id,
    )

    try:
        conversation = (
            await get_or_create_conversation(
                db=db,
                current_user=current_user,
                knowledge_base_id=(
                    request.knowledge_base_id
                ),
                conversation_id=(
                    request.conversation_id
                ),
                question=request.question,
            )
        )

        prepared = await rag_service.prepare_streaming_answer(
            db=db,
            user_id=str(current_user.id),
            knowledge_base_id=str(request.knowledge_base_id),
            query=request.question,
            top_k=request.top_k,
        )

        if request.require_sources and prepared.get("retrieval_mode") == "unavailable":
            raise HTTPException(status_code=503, detail="知识库检索暂不可用，请稍后重试")

        if not prepared["sources"] and not request.require_sources:
            prepared["messages"] = build_general_messages(request.question)
            prepared["fallback_answer"] = None
            prepared["retrieval_mode"] = "general"

        # 保存用户消息时携带 retrieval_mode
        await save_message(
            db=db,
            conversation=conversation,
            role="user",
            content=prepared["query"],
            metadata={
                "retrieval_query": (
                    prepared["retrieval_query"]
                ),
                "retrieval_mode": prepared["retrieval_mode"],
            },
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "流式 RAG 检索准备失败："
            "user_id=%s knowledge_base_id=%s",
            current_user.id,
            request.knowledge_base_id,
        )

        raise HTTPException(
            status_code=500,
            detail="RAG 检索准备失败",
        ) from exc

    async def event_generator() -> AsyncIterator[str]:
        conversation_id_text = str(
            conversation.id
        )

        fallback_answer = prepared.get(
            "fallback_answer"
        )

        if fallback_answer:
            yield format_sse_event(
                event="sources",
                data={
                    "conversation_id": conversation_id_text,
                    "query": prepared["query"],
                    "retrieval_query": prepared["retrieval_query"],
                    "sources": prepared["sources"],
                    "retrieval_mode": prepared["retrieval_mode"],
                },
            )
            await save_message(
                db=db,
                conversation=conversation,
                role="assistant",
                content=fallback_answer,
                citations=prepared["sources"],
                metadata={
                    "retrieval_query": (
                        prepared["retrieval_query"]
                    ),
                    "retrieval_mode": prepared["retrieval_mode"],
                },
            )

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
                    "conversation_id": (
                        conversation_id_text
                    ),
                },
            )

            return

        answer_parts: list[str] = []

        try:
            async for token in (
                deepseek_service.stream_generate(
                    messages=prepared["messages"],
                    temperature=0.1,
                )
            ):
                answer_parts.append(token)

                yield format_sse_event(
                    event="token",
                    data={
                        "content": token,
                    },
                )

            answer = "".join(answer_parts).strip()

            if not answer:
                answer = "模型没有返回有效答案。"

            sources = rag_service.sources_cited_in_answer(
                answer,
                prepared["sources"],
            )

            # ✨ 保存 assistant 消息时使用 retrieval_mode
            await save_message(
                db=db,
                conversation=conversation,
                role="assistant",
                content=answer,
                citations=sources,
                metadata={
                    "retrieval_query": (
                        prepared["retrieval_query"]
                    ),
                    "retrieval_mode": prepared["retrieval_mode"],
                },
            )

            yield format_sse_event(
                event="sources",
                data={
                    "conversation_id": conversation_id_text,
                    "query": prepared["query"],
                    "retrieval_query": prepared["retrieval_query"],
                    "sources": sources,
                    "retrieval_mode": prepared["retrieval_mode"],
                },
            )

            yield format_sse_event(
                event="done",
                data={
                    "status": "completed",
                    "conversation_id": (
                        conversation_id_text
                    ),
                    "sources": sources,
                },
            )

        except Exception:
            logger.exception(
                "DeepSeek 流式回答失败："
                "user_id=%s knowledge_base_id=%s",
                current_user.id,
                request.knowledge_base_id,
            )

            answer = "".join(answer_parts).strip()
            sources = rag_service.sources_cited_in_answer(
                answer,
                prepared["sources"],
            )
            yield format_sse_event(
                event="sources",
                data={
                    "conversation_id": conversation_id_text,
                    "query": prepared["query"],
                    "retrieval_query": prepared["retrieval_query"],
                    "sources": sources,
                    "retrieval_mode": prepared["retrieval_mode"],
                },
            )

            yield format_sse_event(
                event="error",
                data={
                    "message": (
                        "大模型流式回答失败"
                    ),
                    "conversation_id": (
                        conversation_id_text
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

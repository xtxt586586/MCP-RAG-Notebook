import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from openai import APIConnectionError
from pydantic import (
    BaseModel,
    Field,
    field_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    CurrentUser,
    bearer_scheme,
    get_request_access_token,
)
from app.api.v1.chat import (
    get_or_create_conversation,
    save_message_pair,
)
from app.core.database import get_db
from app.services.agent.mcp_agent_service import (
    mcp_agent_service,
)
from app.services.knowledge_base_service import (
    get_current_user_knowledge_base,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agent",
    tags=["MCP Agent"],
)


def format_agent_sse_event(
    *,
    event: str,
    data: dict[str, Any],
) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    )


class AgentChatRequest(BaseModel):
    knowledge_base_id: UUID

    conversation_id: UUID | None = None

    question: str = Field(
        min_length=1,
        max_length=3000,
    )

    @field_validator("question")
    @classmethod
    def validate_question(
        cls,
        value: str,
    ) -> str:
        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError(
                "问题不能为空"
            )

        return normalized_value


class AgentToolStep(BaseModel):
    step: int
    server_name: str
    tool_name: str
    arguments: dict[str, Any]
    is_error: bool
    result_preview: str


class AgentChatResponse(BaseModel):
    conversation_id: str
    query: str
    answer: str
    tool_steps: list[AgentToolStep]
    retrieval_mode: str = "general"
    route_score: float = 0.0
    sources: list[dict[str, Any]] = Field(default_factory=list)
    history_turns: int = 0
    max_steps_reached: bool


@router.post(
    "/chat",
    response_model=AgentChatResponse,
)
async def agent_chat(
    request: AgentChatRequest,
    current_user: CurrentUser,
    http_request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: AsyncSession = Depends(get_db),
) -> AgentChatResponse:
    await get_current_user_knowledge_base(
        db=db,
        user_id=current_user.id,
        requested_id=request.knowledge_base_id,
    )

    try:
        conversation = await get_or_create_conversation(
            db=db,
            current_user=current_user,
            knowledge_base_id=request.knowledge_base_id,
            conversation_id=request.conversation_id,
            question=request.question,
        )

        agent_result = await mcp_agent_service.answer(
            db=db,
            user_id=str(current_user.id),
            knowledge_base_id=str(
                request.knowledge_base_id,
            ),
            question=request.question,
            conversation_id=str(conversation.id),
            access_token=get_request_access_token(http_request, credentials),
        )

        await save_message_pair(
            db=db,
            conversation=conversation,
            question=agent_result["query"],
            answer=agent_result["answer"],
            retrieval_query=str(
                agent_result.get("retrieval_query", agent_result["query"])
            ),
            sources=agent_result.get("sources", []),
            retrieval_mode=str(
                agent_result.get("retrieval_mode", "general")
            ),
            metadata_extra={
                "tool_steps": agent_result["tool_steps"],
                "history_turns": agent_result.get("history_turns", 0),
                "route_score": agent_result.get("route_score", 0.0),
            },
        )

        return AgentChatResponse(
            conversation_id=str(conversation.id),
            **agent_result,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        logger.exception(
            "MCP Agent 外部服务调用失败："
            "user_id=%s knowledge_base_id=%s",
            current_user.id,
            request.knowledge_base_id,
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "MCP Agent 外部服务调用失败："
                f"{str(exc).strip()[:300]}"
            ),
        ) from exc

    except APIConnectionError as exc:
        logger.exception(
            "MCP Agent 模型网络连接失败：user_id=%s knowledge_base_id=%s",
            current_user.id,
            request.knowledge_base_id,
        )
        raise HTTPException(
            status_code=502,
            detail="模型服务暂时不可达，请稍后重试",
        ) from exc

    except Exception as exc:
        logger.exception(
            "MCP Agent 处理失败："
            "user_id=%s knowledge_base_id=%s",
            current_user.id,
            request.knowledge_base_id,
        )

        raise HTTPException(
            status_code=500,
            detail="MCP Agent 处理失败",
        ) from exc


@router.post("/chat/stream")
async def agent_chat_stream(
    request: AgentChatRequest,
    current_user: CurrentUser,
    http_request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await get_current_user_knowledge_base(
        db=db,
        user_id=current_user.id,
        requested_id=request.knowledge_base_id,
    )

    try:
        conversation = await get_or_create_conversation(
            db=db,
            current_user=current_user,
            knowledge_base_id=request.knowledge_base_id,
            conversation_id=request.conversation_id,
            question=request.question,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("MCP Agent 流式会话初始化失败")
        raise HTTPException(
            status_code=500,
            detail="MCP Agent 会话初始化失败",
        ) from exc

    async def event_generator() -> AsyncIterator[str]:
        streamed_answer_parts: list[str] = []
        streamed_sources: list[dict[str, Any]] = []
        streamed_tool_steps: list[dict[str, Any]] = []
        retrieval_mode = "general"
        history_turns = 0
        turn_saved = False

        async def persist_turn(**kwargs: Any) -> None:
            nonlocal turn_saved
            if turn_saved:
                return

            save_task = asyncio.create_task(
                save_message_pair(**kwargs)
            )
            try:
                await asyncio.shield(save_task)
            except asyncio.CancelledError:
                try:
                    await save_task
                except Exception:
                    turn_saved = False
                    raise
                turn_saved = True
                raise
            turn_saved = True

        try:
            # Persist the conversation id before expensive agent work begins so
            # a dropped stream can resume the same conversation on retry.
            await db.commit()
            yield format_agent_sse_event(
                event="conversation",
                data={"conversation_id": str(conversation.id)},
            )

            async for event in mcp_agent_service.stream_answer(
                db=db,
                user_id=str(current_user.id),
                knowledge_base_id=str(request.knowledge_base_id),
                question=request.question,
                conversation_id=str(conversation.id),
                access_token=get_request_access_token(http_request, credentials),
            ):
                event_type = str(event.get("type", "message"))

                if event_type == "token":
                    token_text = str(event.get("content", ""))
                    if token_text:
                        streamed_answer_parts.append(token_text)
                elif event_type == "sources":
                    sources = event.get("sources")
                    if isinstance(sources, list):
                        streamed_sources = sources
                    retrieval_mode = str(
                        event.get("retrieval_mode", retrieval_mode)
                    )
                elif event_type in {"tool_start", "tool_result"}:
                    tool_step = event.get("tool_step")
                    if isinstance(tool_step, dict):
                        step_key = (
                            tool_step.get("step"),
                            tool_step.get("server_name"),
                            tool_step.get("tool_name"),
                        )
                        existing_step = next(
                            (
                                index
                                for index, existing in enumerate(
                                    streamed_tool_steps
                                )
                                if (
                                    existing.get("step"),
                                    existing.get("server_name"),
                                    existing.get("tool_name"),
                                ) == step_key
                            ),
                            None,
                        )
                        if existing_step is None:
                            streamed_tool_steps.append(tool_step)
                        else:
                            streamed_tool_steps[existing_step] = tool_step
                elif event_type == "status":
                    history_turns = int(event.get("history_turns", 0) or 0)
                    retrieval_mode = str(
                        event.get("retrieval_mode", retrieval_mode)
                    )

                if event_type in {"tool_start", "tool_result"}:
                    tool_step = event.get("tool_step")
                    payload = {
                        **event,
                        **(
                            tool_step
                            if isinstance(tool_step, dict)
                            else {}
                        ),
                    }
                    payload.pop("tool_step", None)
                    yield format_agent_sse_event(
                        event=event_type,
                        data=payload,
                    )
                    continue

                if event_type == "final":
                    await persist_turn(
                        db=db,
                        conversation=conversation,
                        question=str(event.get("query", request.question)),
                        answer=str(event.get("answer", "")),
                        retrieval_query=str(event.get("retrieval_query", event.get("query", request.question))),
                        sources=event.get("sources", []),
                        retrieval_mode=str(event.get("retrieval_mode", "agent")),
                        metadata_extra={
                            "tool_steps": event.get("tool_steps", []),
                            "history_turns": event.get("history_turns", 0),
                            "route_score": event.get("route_score", 0.0),
                        },
                    )
                    yield format_agent_sse_event(
                        event="done",
                        data={
                            **event,
                            "conversation_id": str(conversation.id),
                        },
                    )
                    continue

                if event_type == "error":
                    error_message = str(
                        event.get(
                            "message",
                            "MCP Agent 流式回答失败",
                        )
                    )[:500]
                    partial_answer = str(
                        event.get("partial_answer", "")
                    ).strip()
                    await persist_turn(
                        db=db,
                        conversation=conversation,
                        question=request.question,
                        answer=(
                            partial_answer
                            or "本次问答未完成，请重试。"
                        ),
                        retrieval_query=request.question,
                        sources=[],
                        retrieval_mode=str(event.get("retrieval_mode", "general")),
                        metadata_extra={
                            "status": "FAILED",
                            "error_message": error_message,
                            "retryable": bool(
                                event.get("retryable", True)
                            ),
                            "tool_steps": event.get(
                                "tool_steps",
                                [],
                            ),
                            "history_turns": event.get(
                                "history_turns",
                                0,
                            ),
                        },
                    )
                    yield format_agent_sse_event(
                        event="error",
                        data={
                            **event,
                            "conversation_id": str(
                                conversation.id
                            ),
                        },
                    )
                    continue

                yield format_agent_sse_event(
                    event=event_type,
                    data=event,
                )
        except asyncio.CancelledError:
            if not turn_saved:
                partial_answer = "".join(streamed_answer_parts).strip()
                if not partial_answer:
                    partial_answer = "回答已停止，可点击重试重新生成。"

                try:
                    await persist_turn(
                        db=db,
                        conversation=conversation,
                        question=request.question,
                        answer=partial_answer,
                        retrieval_query=request.question,
                        sources=streamed_sources,
                        retrieval_mode=retrieval_mode,
                        metadata_extra={
                            "status": "FAILED",
                            "error_message": "生成已停止",
                            "retryable": True,
                            "tool_steps": streamed_tool_steps,
                            "history_turns": history_turns,
                        },
                    )
                    logger.info(
                        "已保存被取消的流式问答：conversation_id=%s",
                        conversation.id,
                    )
                except Exception:
                    logger.exception(
                        "保存被取消的流式问答失败：conversation_id=%s",
                        conversation.id,
                    )
            raise
        except Exception as exc:
            logger.exception(
                "MCP Agent 流式回答失败：user_id=%s knowledge_base_id=%s",
                current_user.id,
                request.knowledge_base_id,
            )
            error_message = str(exc).strip()[:500] or "MCP Agent 流式回答失败"
            try:
                await persist_turn(
                    db=db,
                    conversation=conversation,
                    question=request.question,
                    answer="本次问答失败，请稍后重试。",
                    retrieval_query=request.question,
                    sources=[],
                    retrieval_mode="general",
                    metadata_extra={
                        "status": "FAILED",
                        "error_message": error_message,
                        "retryable": True,
                        "tool_steps": [],
                        "history_turns": 0,
                    },
                )
            except Exception:
                logger.exception(
                    "保存 MCP Agent 失败会话时出错："
                    "user_id=%s knowledge_base_id=%s",
                    current_user.id,
                    request.knowledge_base_id,
                )
            yield format_agent_sse_event(
                event="error",
                data={
                    "message": error_message,
                    "retryable": True,
                    "conversation_id": str(conversation.id),
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

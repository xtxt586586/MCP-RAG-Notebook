import asyncio
from uuid import uuid4

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app.api.v1 import agent as agent_api
from app.api.v1.agent import AgentChatRequest
from app.models import Conversation, User


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDb:
    def __init__(self, knowledge_base_id):
        self.knowledge_base_id = knowledge_base_id
        self.commit_count = 0

    async def execute(self, _statement):
        return FakeResult(self.knowledge_base_id)

    async def commit(self):
        self.commit_count += 1


def make_request(knowledge_base_id):
    return AgentChatRequest(
        knowledge_base_id=knowledge_base_id,
        question="查询 MCP 相关仓库",
    )


def make_user(user_id):
    return User(
        id=user_id,
        email="agent-test@example.com",
        password_hash="unused",
        is_active=True,
    )


def make_http_request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/v1/agent/chat/stream",
        "headers": [],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1234),
        "scheme": "http",
    })


async def read_stream(response) -> str:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


@pytest.mark.asyncio
async def test_agent_stream_emits_tool_events_and_saves_success(monkeypatch) -> None:
    user_id = uuid4()
    knowledge_base_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
        title="查询 MCP 相关仓库",
        model_name="deepseek-chat",
    )
    saved = []

    async def fake_stream_answer(**_kwargs):
        yield {
            "type": "tool_start",
            "tool_step": {
                "step": 1,
                "server_name": "github",
                "tool_name": "search_repositories",
                "arguments": {"query": "modelcontextprotocol"},
                "is_error": False,
                "result_preview": "",
            },
        }
        yield {
            "type": "tool_result",
            "tool_step": {
                "step": 1,
                "server_name": "github",
                "tool_name": "search_repositories",
                "arguments": {"query": "modelcontextprotocol"},
                "is_error": False,
                "result_preview": "5 repositories found",
            },
        }
        yield {"type": "token", "content": "GitHub 查询完成。"}
        yield {
            "type": "final",
            "query": "查询 MCP 相关仓库",
            "answer": "GitHub 查询完成。",
            "tool_steps": [{
                "step": 1,
                "server_name": "github",
                "tool_name": "search_repositories",
                "arguments": {"query": "modelcontextprotocol"},
                "is_error": False,
                "result_preview": "5 repositories found",
            }],
            "history_turns": 2,
        }

    async def fake_get_or_create_conversation(**_kwargs):
        return conversation

    async def fake_save_message_pair(**kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(
        agent_api,
        "get_or_create_conversation",
        fake_get_or_create_conversation,
    )
    monkeypatch.setattr(
        agent_api,
        "save_message_pair",
        fake_save_message_pair,
    )
    monkeypatch.setattr(
        agent_api.mcp_agent_service,
        "stream_answer",
        fake_stream_answer,
    )

    db = FakeDb(knowledge_base_id)
    response = await agent_api.agent_chat_stream(
        request=make_request(knowledge_base_id),
        current_user=make_user(user_id),
        http_request=make_http_request(),
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="request-token",
        ),
        db=db,
    )

    body = await read_stream(response)

    assert response.media_type == "text/event-stream"
    assert "event: conversation" in body
    assert body.index("event: conversation") < body.index("event: tool_start")
    assert db.commit_count == 1
    assert "event: tool_start" in body
    assert "event: tool_result" in body
    assert "event: token" in body
    assert "GitHub 查询完成。" in body
    assert '"conversation_id": "' + str(conversation.id) + '"' in body
    assert body.count("event: done") == 1
    assert len(saved) == 1
    assert saved[0]["conversation"] is conversation
    assert saved[0]["answer"] == "GitHub 查询完成。"
    assert saved[0]["retrieval_mode"] == "agent"
    assert saved[0]["metadata_extra"]["history_turns"] == 2


@pytest.mark.asyncio
async def test_agent_stream_saves_failed_turn_and_emits_error(monkeypatch) -> None:
    user_id = uuid4()
    knowledge_base_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
        title="查询 MCP 相关仓库",
    )
    saved = []

    async def fake_stream_answer(**_kwargs):
        yield {
            "type": "error",
            "message": "GitHub 暂时不可用",
            "partial_answer": "已完成部分检索",
            "tool_steps": [],
            "history_turns": 0,
            "retryable": True,
        }

    async def fake_get_or_create_conversation(**_kwargs):
        return conversation

    async def fake_save_message_pair(**kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(
        agent_api,
        "get_or_create_conversation",
        fake_get_or_create_conversation,
    )
    monkeypatch.setattr(
        agent_api,
        "save_message_pair",
        fake_save_message_pair,
    )
    monkeypatch.setattr(
        agent_api.mcp_agent_service,
        "stream_answer",
        fake_stream_answer,
    )

    response = await agent_api.agent_chat_stream(
        request=make_request(knowledge_base_id),
        current_user=make_user(user_id),
        http_request=make_http_request(),
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="request-token",
        ),
        db=FakeDb(knowledge_base_id),
    )

    body = await read_stream(response)

    assert "event: error" in body
    assert "GitHub 暂时不可用" in body
    assert "retryable" in body
    assert "event: done" not in body
    assert len(saved) == 1
    assert saved[0]["answer"] == "已完成部分检索"
    assert saved[0]["metadata_extra"]["status"] == "FAILED"
    assert saved[0]["metadata_extra"]["error_message"] == "GitHub 暂时不可用"
    assert saved[0]["metadata_extra"]["retryable"] is True


@pytest.mark.asyncio
async def test_agent_stream_persists_conversation_when_context_setup_raises(monkeypatch) -> None:
    user_id = uuid4()
    knowledge_base_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
        title="1+1 等于多少？",
    )
    saved = []

    async def fake_stream_answer(**_kwargs):
        raise RuntimeError("BGE-M3 模型无法连接 Hugging Face")
        yield  # Make this an async generator that fails before its first event.

    async def fake_get_or_create_conversation(**_kwargs):
        return conversation

    async def fake_save_message_pair(**kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(
        agent_api,
        "get_or_create_conversation",
        fake_get_or_create_conversation,
    )
    monkeypatch.setattr(
        agent_api,
        "save_message_pair",
        fake_save_message_pair,
    )
    monkeypatch.setattr(
        agent_api.mcp_agent_service,
        "stream_answer",
        fake_stream_answer,
    )

    response = await agent_api.agent_chat_stream(
        request=make_request(knowledge_base_id),
        current_user=make_user(user_id),
        http_request=make_http_request(),
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="request-token",
        ),
        db=FakeDb(knowledge_base_id),
    )

    body = await read_stream(response)

    assert "event: error" in body
    assert "BGE-M3 模型无法连接 Hugging Face" in body
    assert '"conversation_id": "' + str(conversation.id) + '"' in body
    assert len(saved) == 1
    assert saved[0]["conversation"] is conversation
    assert saved[0]["answer"] == "本次问答失败，请稍后重试。"
    assert saved[0]["metadata_extra"]["status"] == "FAILED"
    assert saved[0]["metadata_extra"]["retryable"] is True


@pytest.mark.asyncio
async def test_agent_stream_saves_partial_answer_when_cancelled(monkeypatch) -> None:
    user_id = uuid4()
    knowledge_base_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
        title="查询 MCP 相关仓库",
    )
    saved = []

    async def fake_stream_answer(**_kwargs):
        yield {"type": "status", "history_turns": 1, "retrieval_mode": "hybrid"}
        yield {"type": "sources", "sources": [{"title": "MCP 文档"}]}
        yield {"type": "token", "content": "已经找到相关资料。"}
        raise asyncio.CancelledError()

    async def fake_get_or_create_conversation(**_kwargs):
        return conversation

    async def fake_save_message_pair(**kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(
        agent_api,
        "get_or_create_conversation",
        fake_get_or_create_conversation,
    )
    monkeypatch.setattr(
        agent_api,
        "save_message_pair",
        fake_save_message_pair,
    )
    monkeypatch.setattr(
        agent_api.mcp_agent_service,
        "stream_answer",
        fake_stream_answer,
    )

    response = await agent_api.agent_chat_stream(
        request=make_request(knowledge_base_id),
        current_user=make_user(user_id),
        http_request=make_http_request(),
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="request-token",
        ),
        db=FakeDb(knowledge_base_id),
    )

    stream = response.body_iterator
    assert "event: conversation" in await anext(stream)
    assert "event: status" in await anext(stream)
    assert "event: sources" in await anext(stream)
    assert "event: token" in await anext(stream)

    with pytest.raises(asyncio.CancelledError):
        await anext(stream)

    assert len(saved) == 1
    assert saved[0]["answer"] == "已经找到相关资料。"
    assert saved[0]["sources"] == [{"title": "MCP 文档"}]
    assert saved[0]["retrieval_mode"] == "hybrid"
    assert saved[0]["metadata_extra"]["status"] == "FAILED"
    assert saved[0]["metadata_extra"]["retryable"] is True
    assert saved[0]["metadata_extra"]["history_turns"] == 1

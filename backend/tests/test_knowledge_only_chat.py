from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1 import chat


@pytest.mark.asyncio
async def test_knowledge_only_does_not_call_general_model_when_no_sources(monkeypatch):
    user_id, kb_id, conversation_id = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(chat, "ensure_owned_knowledge_base", AsyncMock())
    monkeypatch.setattr(chat, "get_or_create_conversation", AsyncMock(return_value=SimpleNamespace(id=conversation_id)))
    monkeypatch.setattr(chat, "save_message_pair", AsyncMock())
    monkeypatch.setattr(chat.rag_service, "answer", AsyncMock(return_value={
        "query": "测试问题", "retrieval_query": "测试问题", "answer": "根据当前知识库资料无法确定。",
        "retrieval_mode": "general", "sources": [], "route_score": 0.0,
    }))
    general = AsyncMock(side_effect=AssertionError("must not invoke general model"))
    monkeypatch.setattr(chat.deepseek_service, "generate", general)
    response = await chat.chat_with_knowledge_base(
        chat.ChatRequest(knowledge_base_id=kb_id, question="测试问题", require_sources=True),
        current_user=SimpleNamespace(id=user_id), db=object(),
    )
    assert response.answer == "根据当前知识库资料无法确定。"
    assert response.sources == []
    general.assert_not_awaited()


@pytest.mark.asyncio
async def test_knowledge_only_stream_returns_no_sources_fallback(monkeypatch):
    user_id, kb_id, conversation_id = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(chat, "ensure_owned_knowledge_base", AsyncMock())
    monkeypatch.setattr(chat, "get_or_create_conversation", AsyncMock(return_value=SimpleNamespace(id=conversation_id)))
    monkeypatch.setattr(chat, "save_message", AsyncMock())
    monkeypatch.setattr(chat.rag_service, "prepare_streaming_answer", AsyncMock(return_value={
        "query": "测试问题", "retrieval_query": "测试问题", "messages": None,
        "fallback_answer": "根据当前知识库资料无法确定。", "retrieval_mode": "general", "sources": [],
    }))
    def unexpected_stream(**kwargs):
        raise AssertionError("must not invoke general model")
    monkeypatch.setattr(chat.deepseek_service, "stream_generate", unexpected_stream)
    response = await chat.stream_chat_with_knowledge_base(
        chat.ChatRequest(knowledge_base_id=kb_id, question="测试问题", require_sources=True),
        current_user=SimpleNamespace(id=user_id), db=object(),
    )
    chunks = [part async for part in response.body_iterator]
    text = "".join(part.decode() if isinstance(part, bytes) else part for part in chunks)
    assert "根据当前知识库资料无法确定。" in text
    assert "event: done" in text


@pytest.mark.asyncio
async def test_knowledge_only_surfaces_retrieval_failure(monkeypatch):
    user_id, kb_id = uuid4(), uuid4()
    monkeypatch.setattr(chat, "ensure_owned_knowledge_base", AsyncMock())
    monkeypatch.setattr(chat, "get_or_create_conversation", AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    monkeypatch.setattr(chat.rag_service, "answer", AsyncMock(return_value={
        "query": "测试问题", "retrieval_query": "测试问题", "answer": "根据当前知识库资料无法确定。",
        "retrieval_mode": "unavailable", "sources": [], "route_score": 0.0,
    }))
    with pytest.raises(HTTPException) as exc:
        await chat.chat_with_knowledge_base(
            chat.ChatRequest(knowledge_base_id=kb_id, question="测试问题", require_sources=True),
            current_user=SimpleNamespace(id=user_id), db=object(),
        )
    assert exc.value.status_code == 503

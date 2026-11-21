from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api.v1 import conversations as conversations_api
from app.models import Conversation, Message
from app.services.agent.langchain_agent_service import LangChainAgentService


def make_message(role: str, content: str) -> Message:
    return Message(
        id=uuid4(),
        conversation_id=uuid4(),
        role=role,
        content=content,
        created_at=datetime.now(timezone.utc),
    )


def test_history_messages_preserve_pairs_and_bound_turns() -> None:
    messages = [
        make_message("user", "第一问"),
        make_message("assistant", "第一答"),
        make_message("user", "第二问"),
        make_message("assistant", "第二答"),
        make_message("user", "第三问"),
        make_message("assistant", "第三答"),
    ]

    result = LangChainAgentService._history_messages(messages, 2)

    assert result == [
        {"role": "user", "content": "第二问"},
        {"role": "assistant", "content": "第二答"},
        {"role": "user", "content": "第三问"},
        {"role": "assistant", "content": "第三答"},
    ]


def test_history_messages_pairs_same_timestamp_user_and_assistant() -> None:
    timestamp = datetime.now(timezone.utc)
    assistant = make_message("assistant", "第一答")
    assistant.created_at = timestamp
    user = make_message("user", "第一问")
    user.created_at = timestamp

    result = LangChainAgentService._history_messages(
        [user, assistant],
        8,
    )

    assert result == [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
    ]


def test_history_messages_ignores_unpaired_and_tool_messages() -> None:
    messages = [
        make_message("user", "未完成的问题"),
        make_message("tool", "工具内部结果"),
        make_message("user", "完整问题"),
        make_message("assistant", "完整回答"),
    ]

    result = LangChainAgentService._history_messages(messages, 8)

    assert result == [
        {"role": "user", "content": "完整问题"},
        {"role": "assistant", "content": "完整回答"},
    ]


def test_history_messages_ignores_failed_turns() -> None:
    failed_user = make_message("user", "失败的问题")
    failed_user.extra_metadata = {"status": "FAILED"}
    failed_answer = make_message("assistant", "部分回答")
    failed_answer.extra_metadata = {"status": "FAILED"}

    result = LangChainAgentService._history_messages(
        [
            failed_user,
            failed_answer,
            make_message("user", "成功的问题"),
            make_message("assistant", "成功的回答"),
        ],
        8,
    )

    assert result == [
        {"role": "user", "content": "成功的问题"},
        {"role": "assistant", "content": "成功的回答"},
    ]


@pytest.mark.parametrize(
    "question",
    [
        "整理为笔记",
        "请把这些内容整理成笔记",
        "保存这些内容",
        "帮我保存成笔记",
    ],
)
def test_note_intent_recognizes_save_phrases(question: str) -> None:
    assert LangChainAgentService._has_note_intent(question)


class _MemoryDb:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


class _HistoryResult:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _HistoryDb:
    def __init__(self, conversation, messages, max_turns=1):
        self.conversation = conversation
        self.messages = messages
        self.max_turns = max_turns
        self.statements = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(str(statement))
        call_number = (len(self.statements) - 1) % 3 + 1
        if call_number == 1:
            return _HistoryResult(scalar=self.conversation)
        if call_number == 2:
            return _HistoryResult(rows=self.messages)
        return _HistoryResult(scalar=self.max_turns)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_clear_memory_preserves_messages_and_resets_summary(monkeypatch) -> None:
    conversation = type(
        "ConversationStub",
        (),
        {
            "memory_summary": "旧摘要",
            "memory_summary_turns": 6,
            "memory_reset_at": None,
        },
    )()
    db = _MemoryDb()

    async def fake_get_owned_conversation(**_kwargs):
        return conversation

    monkeypatch.setattr(
        conversations_api,
        "get_owned_conversation",
        fake_get_owned_conversation,
    )

    result = await conversations_api.clear_conversation_memory(
        conversation_id=uuid4(),
        current_user=object(),
        db=db,
    )

    assert result["memory_reset"] is True
    assert result["cleared_messages"] == 0
    assert conversation.memory_summary is None
    assert conversation.memory_summary_turns == 0
    assert conversation.memory_reset_at is not None
    assert conversation.memory_reset_at.tzinfo is not None
    assert db.commits == 1


@pytest.mark.asyncio
async def test_agent_history_respects_reset_boundary_and_summary_progress() -> None:
    conversation_id = uuid4()
    user_id = uuid4()
    knowledge_base_id = uuid4()
    conversation = Conversation(
        id=conversation_id,
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
        memory_reset_at=datetime.now(timezone.utc),
    )
    messages = []
    for question, answer in (("新问题 1", "新回答 1"), ("新问题 2", "新回答 2")):
        user_message = make_message("user", question)
        assistant_message = make_message("assistant", answer)
        user_message.conversation_id = conversation_id
        assistant_message.conversation_id = conversation_id
        messages.extend((user_message, assistant_message))

    db = _HistoryDb(conversation, messages, max_turns=1)
    service = LangChainAgentService()

    first = await service._load_history(
        db=db,
        conversation_id=str(conversation_id),
        user_id=str(user_id),
        knowledge_base_id=str(knowledge_base_id),
    )
    second = await service._load_history(
        db=db,
        conversation_id=str(conversation_id),
        user_id=str(user_id),
        knowledge_base_id=str(knowledge_base_id),
    )

    assert any("messages.created_at >" in statement for statement in db.statements)
    assert any("CASE" in statement for statement in db.statements)
    assert [item["content"] for item in first if item["role"] != "system"] == [
        "新问题 2",
        "新回答 2",
    ]
    assert [item["content"] for item in second if item["role"] != "system"] == [
        "新问题 2",
        "新回答 2",
    ]
    assert conversation.memory_summary_turns == 1
    assert db.commits == 1

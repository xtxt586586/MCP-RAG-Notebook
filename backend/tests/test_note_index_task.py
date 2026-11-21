from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.workers import tasks


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, note):
        self.note = note

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _statement):
        return FakeResult(self.note)

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_note_vector_task_indexes_the_latest_owned_note(monkeypatch):
    note = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        knowledge_base_id=uuid4(),
        title="RAG 复盘",
        content="笔记内容",
        extra_metadata={"tags": ["RAG"]},
        vector_index_status="pending",
        vector_index_error=None,
    )
    session = FakeSession(note)
    replace_vectors = AsyncMock()
    dispose_engine = AsyncMock()
    monkeypatch.setattr(tasks, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(
        tasks.milvus_indexing_service,
        "replace_note_vectors",
        replace_vectors,
    )
    monkeypatch.setattr(tasks, "engine", SimpleNamespace(dispose=dispose_engine))

    result = await tasks._index_note_vectors(note.id, note.user_id)

    assert result == {"status": "indexed", "note_id": str(note.id)}
    assert note.vector_index_status == "ready"
    assert note.vector_index_error is None
    replace_vectors.assert_awaited_once_with(
        note_id=str(note.id),
        user_id=str(note.user_id),
        knowledge_base_id=str(note.knowledge_base_id),
        title=note.title,
        content=note.content,
        metadata=note.extra_metadata,
    )
    dispose_engine.assert_awaited_once()


@pytest.mark.asyncio
async def test_note_vector_task_skips_notes_that_were_deleted(monkeypatch):
    replace_vectors = AsyncMock()
    dispose_engine = AsyncMock()
    monkeypatch.setattr(tasks, "AsyncSessionLocal", lambda: FakeSession(None))
    monkeypatch.setattr(
        tasks.milvus_indexing_service,
        "replace_note_vectors",
        replace_vectors,
    )
    monkeypatch.setattr(tasks, "engine", SimpleNamespace(dispose=dispose_engine))

    result = await tasks._index_note_vectors(uuid4(), uuid4())

    assert result["status"] == "skipped"
    replace_vectors.assert_not_awaited()
    dispose_engine.assert_awaited_once()


@pytest.mark.asyncio
async def test_note_index_failure_is_persisted_for_the_owner(monkeypatch):
    note = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        vector_index_status="indexing",
        vector_index_error=None,
    )
    session = FakeSession(note)
    dispose_engine = AsyncMock()
    monkeypatch.setattr(tasks, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(tasks, "engine", SimpleNamespace(dispose=dispose_engine))

    await tasks._mark_note_index_failed(note.id, note.user_id)

    assert note.vector_index_status == "failed"
    assert note.vector_index_error == "索引失败，笔记已保存，可重试。"
    dispose_engine.assert_awaited_once()

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1 import documents as documents_api
from app.models import Document, IngestionTask, User


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDb:
    def __init__(self, task=None):
        self.task = task
        self.commits = 0
        self.refreshes = 0

    async def execute(self, _statement):
        return FakeResult(self.task)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _instance):
        self.refreshes += 1


def make_user(user_id):
    return User(
        id=user_id,
        email="retry-test@example.com",
        password_hash="unused",
        is_active=True,
    )


def make_document(status="PARSE_FAILED"):
    return Document(
        id=uuid4(),
        knowledge_base_id=uuid4(),
        file_name="failed.md",
        object_name="documents/failed.md",
        mime_type="text/markdown",
        size_bytes=12,
        status=status,
    )


@pytest.mark.asyncio
async def test_retry_requeues_owned_failed_document(monkeypatch):
    document = make_document("PARSE_FAILED")
    task = IngestionTask(
        id=uuid4(),
        document_id=document.id,
        status="FAILED",
        progress=98,
        error_message="parse failed",
        celery_task_id="old-task",
    )
    db = FakeDb(task)
    queued = []
    user = make_user(uuid4())

    async def fake_get_owned_document(**_kwargs):
        return document

    def fake_delay(document_id, user_id):
        queued.append((document_id, user_id))
        return SimpleNamespace(id="new-task")

    async def fake_detail(*_args):
        return {"id": str(document.id), "status": document.status}

    monkeypatch.setattr(documents_api, "get_owned_document", fake_get_owned_document)
    monkeypatch.setattr(documents_api.ingest_document, "delay", fake_delay)
    monkeypatch.setattr(documents_api, "get_document_detail", fake_detail)

    result = await documents_api.retry_document_ingestion(
        document_id=document.id,
        current_user=user,
        db=db,
    )

    assert result["status"] == "UPLOADED"
    assert document.status == "UPLOADED"
    assert task.status == "PENDING"
    assert task.progress == 0
    assert task.error_message is None
    assert task.celery_task_id == "new-task"
    assert queued == [(str(document.id), str(user.id))]
    assert db.commits == 2
    assert db.refreshes == 1


@pytest.mark.asyncio
async def test_retry_rejects_non_failed_document(monkeypatch):
    document = make_document("READY")
    db = FakeDb(IngestionTask(document_id=document.id, status="SUCCESS"))

    async def fake_get_owned_document(**_kwargs):
        return document

    monkeypatch.setattr(documents_api, "get_owned_document", fake_get_owned_document)

    with pytest.raises(HTTPException) as exc_info:
        await documents_api.retry_document_ingestion(
            document_id=document.id,
            current_user=make_user(uuid4()),
            db=db,
        )

    assert exc_info.value.status_code == 409
    assert "不允许重试" in str(exc_info.value.detail)
    assert db.commits == 0


@pytest.mark.asyncio
async def test_retry_does_not_expose_other_users_document(monkeypatch):
    db = FakeDb()

    async def fake_get_owned_document(**_kwargs):
        return None

    monkeypatch.setattr(documents_api, "get_owned_document", fake_get_owned_document)

    with pytest.raises(HTTPException) as exc_info:
        await documents_api.retry_document_ingestion(
            document_id=uuid4(),
            current_user=make_user(uuid4()),
            db=db,
        )

    assert exc_info.value.status_code == 404
    assert db.commits == 0

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.graph_rebuild_service import update_graph_rebuild_task


class FakeResult:
    def __init__(self, job):
        self.job = job

    def scalar_one_or_none(self):
        return self.job


class FakeSession:
    def __init__(self, job):
        self.job = job
        self.commit_count = 0

    async def execute(self, _statement):
        return FakeResult(self.job)

    async def commit(self):
        self.commit_count += 1


@pytest.mark.asyncio
async def test_graph_rebuild_tracks_progress_and_ignores_duplicate_task_results():
    job = SimpleNamespace(
        id=uuid4(),
        status="pending",
        total_count=2,
        completed_count=0,
        failed_count=0,
        processed_task_ids=[],
        finished_at=None,
    )
    db = FakeSession(job)

    await update_graph_rebuild_task(
        db, job_id=job.id, task_id="task-1", started=True
    )
    await update_graph_rebuild_task(db, job_id=job.id, task_id="task-1")
    await update_graph_rebuild_task(db, job_id=job.id, task_id="task-1")

    assert job.status == "running"
    assert job.completed_count == 1
    assert job.processed_task_ids == ["task-1"]

    await update_graph_rebuild_task(
        db, job_id=job.id, task_id="task-2", failed=True
    )

    assert job.status == "partial"
    assert job.completed_count == 2
    assert job.failed_count == 1
    assert isinstance(job.finished_at, datetime)


@pytest.mark.asyncio
async def test_graph_rebuild_with_no_items_is_not_changed_by_late_updates():
    job = SimpleNamespace(
        id=uuid4(),
        status="completed",
        total_count=0,
        completed_count=0,
        failed_count=0,
        processed_task_ids=[],
        finished_at=datetime.now(),
    )
    db = FakeSession(job)

    await update_graph_rebuild_task(db, job_id=job.id, task_id="late-task")

    assert job.status == "completed"
    assert job.completed_count == 0
    assert db.commit_count == 0

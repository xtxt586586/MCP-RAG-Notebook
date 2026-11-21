from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GraphRebuildJob


async def update_graph_rebuild_task(
    db: AsyncSession,
    *,
    job_id: UUID,
    task_id: str,
    started: bool = False,
    failed: bool = False,
) -> None:
    result = await db.execute(
        select(GraphRebuildJob)
        .where(GraphRebuildJob.id == job_id)
        .with_for_update()
    )
    job = result.scalar_one_or_none()
    if job is None or job.status in {"completed", "partial", "failed"}:
        return

    if started:
        job.status = "running"
        await db.commit()
        return

    processed_task_ids = list(job.processed_task_ids or [])
    if task_id in processed_task_ids:
        return

    processed_task_ids.append(task_id)
    job.processed_task_ids = processed_task_ids
    job.completed_count = min(job.total_count, job.completed_count + 1)
    if failed:
        job.failed_count = min(job.total_count, job.failed_count + 1)

    if job.completed_count >= job.total_count:
        if job.failed_count == job.total_count:
            job.status = "failed"
        elif job.failed_count:
            job.status = "partial"
        else:
            job.status = "completed"
        job.finished_at = datetime.now(timezone.utc)
    else:
        job.status = "running"

    await db.commit()

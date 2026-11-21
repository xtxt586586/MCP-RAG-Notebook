from typing import Any
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.dependencies import CurrentUser
from app.core.database import get_db
from app.models import (
    Document,
    GraphEntity,
    GraphMention,
    GraphRelation,
    GraphRebuildJob,
    Note,
)
from app.services.knowledge_base_service import get_current_user_knowledge_base
from app.services.graph_rebuild_service import update_graph_rebuild_task
from app.workers.tasks import extract_document_graph, extract_note_graph


router = APIRouter(prefix="/knowledge-graph", tags=["知识图谱"])


@router.post("/rebuild", status_code=status.HTTP_202_ACCEPTED)
async def rebuild_knowledge_graph(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    knowledge_base_id: UUID = Query(...),
) -> dict[str, Any]:
    knowledge_base = await get_current_user_knowledge_base(
        db=db,
        user_id=current_user.id,
        requested_id=knowledge_base_id,
    )
    notes = list((await db.execute(
        select(Note.id).where(
            Note.user_id == current_user.id,
            Note.knowledge_base_id == knowledge_base.id,
        )
    )).scalars().all())
    documents = list((await db.execute(
        select(Document.id).where(
            Document.knowledge_base_id == knowledge_base.id,
            Document.status == "READY",
        )
    )).scalars().all())

    total_count = len(notes) + len(documents)
    job = GraphRebuildJob(
        user_id=current_user.id,
        knowledge_base_id=knowledge_base.id,
        status="pending" if total_count else "completed",
        total_count=total_count,
        finished_at=None if total_count else datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    queued_notes = 0
    queued_documents = 0
    for note_id in notes:
        task_id = str(uuid4())
        try:
            extract_note_graph.apply_async(
                args=[str(note_id), str(current_user.id), str(job.id)],
                task_id=task_id,
            )
            queued_notes += 1
        except Exception:
            await update_graph_rebuild_task(
                db,
                job_id=job.id,
                task_id=task_id,
                failed=True,
            )
    for document_id in documents:
        task_id = str(uuid4())
        try:
            extract_document_graph.apply_async(
                args=[str(document_id), str(current_user.id), str(job.id)],
                task_id=task_id,
            )
            queued_documents += 1
        except Exception:
            await update_graph_rebuild_task(
                db,
                job_id=job.id,
                task_id=task_id,
                failed=True,
            )

    await db.refresh(job)
    return {
        "job_id": str(job.id),
        "status": job.status,
        "total_count": job.total_count,
        "completed_count": job.completed_count,
        "failed_count": job.failed_count,
        "queued_notes": queued_notes,
        "queued_documents": queued_documents,
    }


@router.get("/rebuild/{job_id}")
async def get_graph_rebuild_status(
    job_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(GraphRebuildJob).where(
            GraphRebuildJob.id == job_id,
            GraphRebuildJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="图谱重建任务不存在")
    return {
        "job_id": str(job.id),
        "status": job.status,
        "total_count": job.total_count,
        "completed_count": job.completed_count,
        "failed_count": job.failed_count,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


@router.get("")
async def get_knowledge_graph(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    knowledge_base_id: UUID = Query(...),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    knowledge_base = await get_current_user_knowledge_base(
        db=db,
        user_id=current_user.id,
        requested_id=knowledge_base_id,
    )

    entity_result = await db.execute(
        select(GraphEntity)
        .where(
            GraphEntity.user_id == current_user.id,
            GraphEntity.knowledge_base_id == knowledge_base.id,
        )
        .order_by(GraphEntity.name)
        .limit(limit)
    )
    entities = list(entity_result.scalars().all())
    entity_ids = [entity.id for entity in entities]
    if not entity_ids:
        return {
            "knowledge_base_id": str(knowledge_base.id),
            "nodes": [],
            "edges": [],
            "count": {"entities": 0, "relations": 0},
        }

    mention_counts = dict(
        (await db.execute(
            select(
                GraphMention.entity_id,
                func.count(func.distinct(GraphMention.source_id)),
            )
            .where(
                GraphMention.user_id == current_user.id,
                GraphMention.knowledge_base_id == knowledge_base.id,
                GraphMention.entity_id.in_(entity_ids),
            )
            .group_by(GraphMention.entity_id)
        )).all()
    )
    source_entity = aliased(GraphEntity)
    target_entity = aliased(GraphEntity)
    relation_result = await db.execute(
        select(GraphRelation, source_entity, target_entity)
        .join(source_entity, GraphRelation.source_entity_id == source_entity.id)
        .join(target_entity, GraphRelation.target_entity_id == target_entity.id)
        .where(
            GraphRelation.user_id == current_user.id,
            GraphRelation.knowledge_base_id == knowledge_base.id,
            GraphRelation.source_entity_id.in_(entity_ids),
            GraphRelation.target_entity_id.in_(entity_ids),
        )
        .order_by(GraphRelation.created_at.desc())
        .limit(limit * 3)
    )
    relations = relation_result.all()
    note_ids = {
        relation.source_id
        for relation, _, _ in relations
        if relation.source_type == "note"
    }
    document_ids = {
        relation.source_id
        for relation, _, _ in relations
        if relation.source_type == "document"
    }
    source_titles: dict[tuple[str, UUID], str] = {}
    if note_ids:
        note_rows = await db.execute(
            select(Note.id, Note.title).where(
                Note.id.in_(note_ids),
                Note.user_id == current_user.id,
                Note.knowledge_base_id == knowledge_base.id,
            )
        )
        source_titles.update({("note", row.id): row.title for row in note_rows})
    if document_ids:
        document_rows = await db.execute(
            select(Document.id, Document.file_name).where(
                Document.id.in_(document_ids),
                Document.knowledge_base_id == knowledge_base.id,
            )
        )
        source_titles.update({("document", row.id): row.file_name for row in document_rows})

    return {
        "knowledge_base_id": str(knowledge_base.id),
        "nodes": [
            {
                "id": str(entity.id),
                "name": entity.name,
                "type": entity.entity_type,
                "description": entity.description,
                "source_count": int(mention_counts.get(entity.id, 0)),
            }
            for entity in entities
        ],
        "edges": [
            {
                "id": str(relation.id),
                "source": str(relation.source_entity_id),
                "target": str(relation.target_entity_id),
                "predicate": relation.predicate,
                "evidence": relation.evidence,
                "source_type": relation.source_type,
                "source_id": str(relation.source_id),
                "source_entity_name": subject.name,
                "target_entity_name": object_.name,
                "evidence_source_title": source_titles.get(
                    (relation.source_type, relation.source_id),
                    "未知来源",
                ),
            }
            for relation, subject, object_ in relations
        ],
        "count": {
            "entities": len(entities),
            "relations": len(relations),
        },
    }

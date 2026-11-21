import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.database import (
    AsyncSessionLocal,
    engine,
)
from app.models import Document, KnowledgeBase, Note
from app.services.indexing.document_indexing_service import (
    document_indexing_service,
)
from app.services.parsing.parsing_service import (
    document_parsing_service,
)
from app.services.knowledge_graph_service import knowledge_graph_service
from app.services.graph_rebuild_service import update_graph_rebuild_task
from app.services.storage.minio_service import minio_storage
from app.services.vector_store.milvus_indexing_service import (
    milvus_indexing_service,
)
from app.workers.celery_app import celery_app


@celery_app.task(
    name="app.workers.tasks.health_check",
)
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "worker": "celery",
    }


@celery_app.task(
    name="app.workers.tasks.add_numbers",
)
def add_numbers(
    first: int,
    second: int,
) -> int:
    return first + second


async def _ingest_document(
    *,
    document_id: UUID,
    user_id: UUID,
) -> dict:
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Document)
                .join(
                    KnowledgeBase,
                    Document.knowledge_base_id
                    == KnowledgeBase.id,
                )
                .where(
                    Document.id == document_id,
                    KnowledgeBase.user_id
                    == user_id,
                )
            )

            document = result.scalar_one_or_none()

            if document is None:
                raise ValueError(
                    "文档不存在或不属于当前用户"
                )

            if document.status == "READY":
                return {
                    "document_id": str(document.id),
                    "status": "READY",
                    "message": "文档已经完成索引",
                }

            parse_statuses = {
                "UPLOADED",
                "PARSE_FAILED",
            }

            if document.status in parse_statuses:
                await document_parsing_service.parse(
                    db,
                    user_id=user_id,
                    document=document,
                )

                await db.refresh(document)

            index_statuses = {
                "PARSED",
                "EMBEDDING_FAILED",
                "INDEXING_FAILED",
            }

            if document.status not in index_statuses:
                raise ValueError(
                    "文档当前状态无法继续摄取："
                    f"{document.status}"
                )

            result_data = (
                await document_indexing_service
                .index_document(
                    db,
                    document=document,
                )
            )

            if settings.graph_auto_extract_enabled:
                try:
                    await _replace_document_graph(db, document, user_id)
                except Exception:
                    # Graph indexing is additive; it must not mark a successfully
                    # vectorized document as failed.
                    import logging

                    logging.getLogger(__name__).exception(
                        "文档 GraphRAG 索引失败 document_id=%s",
                        document.id,
                    )

            return result_data

    finally:
        # Celery 的同步任务每次使用 asyncio.run()
        # 创建事件循环，因此任务结束时释放连接池。
        await engine.dispose()


async def _replace_document_graph(db, document: Document, user_id: UUID) -> None:
    metadata = dict(document.extra_metadata or {})
    chunks_object_name = metadata.get("chunks_object_name")
    if not chunks_object_name:
        return
    payload = await minio_storage.download_bytes(chunks_object_name)
    chunks = json.loads(payload.decode("utf-8"))
    content = "\n\n".join(
        str(chunk.get("content", ""))
        for chunk in chunks
        if isinstance(chunk, dict) and chunk.get("content")
    )
    if not content.strip():
        return
    await knowledge_graph_service.replace_source(
        db,
        user_id=user_id,
        knowledge_base_id=document.knowledge_base_id,
        source_type="document",
        source_id=document.id,
        title=document.file_name,
        content=content,
    )


async def _extract_note_graph(note_id: UUID, user_id: UUID) -> dict:
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Note).where(
                    Note.id == note_id,
                    Note.user_id == user_id,
                    Note.knowledge_base_id.is_not(None),
                )
            )
            note = result.scalar_one_or_none()
            if note is None:
                return {"status": "skipped", "note_id": str(note_id)}
            counts = await knowledge_graph_service.replace_source(
                db,
                user_id=user_id,
                knowledge_base_id=note.knowledge_base_id,
                source_type="note",
                source_id=note.id,
                title=note.title,
                content=note.content,
            )
            return {"status": "indexed", "note_id": str(note_id), **counts}
    finally:
        await engine.dispose()


async def _index_note_vectors(note_id: UUID, user_id: UUID) -> dict:
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Note).where(
                    Note.id == note_id,
                    Note.user_id == user_id,
                )
            )
            note = result.scalar_one_or_none()
            if note is None:
                return {"status": "skipped", "note_id": str(note_id)}

            if note.knowledge_base_id is None:
                note.vector_index_status = "skipped"
                note.vector_index_error = None
                await db.commit()
                return {"status": "skipped", "note_id": str(note_id)}

            note.vector_index_status = "indexing"
            note.vector_index_error = None
            await db.commit()

            await milvus_indexing_service.replace_note_vectors(
                note_id=str(note.id),
                user_id=str(note.user_id),
                knowledge_base_id=str(note.knowledge_base_id),
                title=note.title,
                content=note.content,
                metadata=note.extra_metadata,
            )
            note.vector_index_status = "ready"
            note.vector_index_error = None
            await db.commit()
            return {"status": "indexed", "note_id": str(note.id)}
    finally:
        await engine.dispose()


async def _mark_note_index_failed(note_id: UUID, user_id: UUID) -> None:
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Note).where(
                    Note.id == note_id,
                    Note.user_id == user_id,
                )
            )
            note = result.scalar_one_or_none()
            if note is None:
                return
            note.vector_index_status = "failed"
            note.vector_index_error = "索引失败，笔记已保存，可重试。"
            await db.commit()
    finally:
        await engine.dispose()


async def _record_graph_rebuild_task(
    job_id: UUID,
    task_id: str,
    *,
    started: bool = False,
    failed: bool = False,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await update_graph_rebuild_task(
                db,
                job_id=job_id,
                task_id=task_id,
                started=started,
                failed=failed,
            )
    finally:
        await engine.dispose()


async def _extract_document_graph(document_id: UUID, user_id: UUID) -> dict:
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Document)
                .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
                .where(
                    Document.id == document_id,
                    KnowledgeBase.user_id == user_id,
                    Document.status == "READY",
                )
            )
            document = result.scalar_one_or_none()
            if document is None:
                return {"status": "skipped", "document_id": str(document_id)}
            await _replace_document_graph(db, document, user_id)
            return {"status": "indexed", "document_id": str(document_id)}
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True,
    name="app.workers.tasks.ingest_document",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def ingest_document(
    self,
    document_id: str,
    user_id: str,
) -> dict:
    try:
        parsed_document_id = UUID(document_id)
        parsed_user_id = UUID(user_id)

        return asyncio.run(
            _ingest_document(
                document_id=parsed_document_id,
                user_id=parsed_user_id,
            )
        )

    except Exception as exc:
        retry_number = self.request.retries + 1
        countdown = min(
            60,
            2 ** retry_number,
        )

        raise self.retry(
            exc=exc,
            countdown=countdown,
        )


@celery_app.task(
    bind=True,
    name="app.workers.tasks.extract_note_graph",
    max_retries=3,
    acks_late=True,
)
def extract_note_graph(
    self,
    note_id: str,
    user_id: str,
    rebuild_job_id: str | None = None,
) -> dict:
    task_id = self.request.id or f"note:{note_id}"
    try:
        if rebuild_job_id:
            asyncio.run(
                _record_graph_rebuild_task(
                    UUID(rebuild_job_id), task_id, started=True
                )
            )
        result = asyncio.run(_extract_note_graph(UUID(note_id), UUID(user_id)))
        if rebuild_job_id:
            asyncio.run(
                _record_graph_rebuild_task(UUID(rebuild_job_id), task_id)
            )
        return result
    except Exception as exc:
        if rebuild_job_id and self.request.retries >= self.max_retries:
            try:
                asyncio.run(
                    _record_graph_rebuild_task(
                        UUID(rebuild_job_id), task_id, failed=True
                    )
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "无法保存图谱重建任务失败状态 job_id=%s",
                    rebuild_job_id,
                )
        raise self.retry(exc=exc, countdown=min(60, 2 ** (self.request.retries + 1)))


@celery_app.task(
    bind=True,
    name="app.workers.tasks.index_note_vectors",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def index_note_vectors(self, note_id: str, user_id: str) -> dict:
    try:
        return asyncio.run(_index_note_vectors(UUID(note_id), UUID(user_id)))
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            try:
                asyncio.run(
                    _mark_note_index_failed(UUID(note_id), UUID(user_id))
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "无法保存笔记索引失败状态 note_id=%s",
                    note_id,
                )
        raise self.retry(exc=exc, countdown=min(60, 2 ** (self.request.retries + 1)))


@celery_app.task(
    bind=True,
    name="app.workers.tasks.extract_document_graph",
    max_retries=3,
    acks_late=True,
)
def extract_document_graph(
    self,
    document_id: str,
    user_id: str,
    rebuild_job_id: str | None = None,
) -> dict:
    task_id = self.request.id or f"document:{document_id}"
    try:
        if rebuild_job_id:
            asyncio.run(
                _record_graph_rebuild_task(
                    UUID(rebuild_job_id), task_id, started=True
                )
            )
        result = asyncio.run(_extract_document_graph(UUID(document_id), UUID(user_id)))
        if rebuild_job_id:
            asyncio.run(
                _record_graph_rebuild_task(UUID(rebuild_job_id), task_id)
            )
        return result
    except Exception as exc:
        if rebuild_job_id and self.request.retries >= self.max_retries:
            try:
                asyncio.run(
                    _record_graph_rebuild_task(
                        UUID(rebuild_job_id), task_id, failed=True
                    )
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "无法保存图谱重建任务失败状态 job_id=%s",
                    rebuild_job_id,
                )
        raise self.retry(exc=exc, countdown=min(60, 2 ** (self.request.retries + 1)))

import json
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Document, IngestionTask
from app.services.embedding.bge_m3_service import (
    DENSE_VECTOR_DIMENSION,
    bge_m3_embedding_service,
)
from app.services.storage.minio_service import minio_storage
from app.services.vector_store.milvus_indexing_service import (
    milvus_indexing_service,
)


logger = logging.getLogger(__name__)


class DocumentIndexingService:
    async def _get_or_create_task(
        self,
        db: AsyncSession,
        document_id: UUID,
    ) -> IngestionTask:
        result = await db.execute(
            select(IngestionTask)
            .where(
                IngestionTask.document_id == document_id
            )
            .order_by(
                IngestionTask.created_at.desc()
            )
            .limit(1)
        )

        task = result.scalar_one_or_none()

        if task is None:
            task = IngestionTask(
                document_id=document_id,
                status="PENDING",
                progress=40,
            )

            db.add(task)
            await db.flush()

        return task

    async def index_document(
        self,
        db: AsyncSession,
        *,
        document: Document,
    ) -> dict:
        task = await self._get_or_create_task(
            db,
            document.id,
        )

        current_stage = "embedding"

        document.status = "EMBEDDING"
        task.status = "RUNNING"
        task.progress = 50
        task.error_message = None

        await db.commit()

        try:
            document_metadata = dict(
                document.extra_metadata or {}
            )

            chunks_object_name = document_metadata.get(
                "chunks_object_name"
            )

            if not chunks_object_name:
                raise ValueError(
                    "文档没有 chunks_object_name，"
                    "请先完成文档解析"
                )

            chunks_data = await minio_storage.download_bytes(
                chunks_object_name
            )

            chunks = json.loads(
                chunks_data.decode("utf-8")
            )

            if not isinstance(chunks, list) or not chunks:
                raise ValueError("chunks.json 内容无效")

            texts = [
                chunk["content"]
                for chunk in chunks
            ]

            dense_vectors, sparse_vectors = (
                await bge_m3_embedding_service.encode(texts)
            )

            task.progress = 75
            document.status = "INDEXING"

            await db.commit()

            current_stage = "indexing"

            records: list[dict] = []

            for chunk, dense_vector, sparse_vector in zip(
                chunks,
                dense_vectors,
                sparse_vectors,
            ):
                records.append(
                    {
                        "id": chunk["id"],
                        "user_id": chunk["user_id"],
                        "knowledge_base_id": (
                            chunk["knowledge_base_id"]
                        ),
                        "document_id": chunk["document_id"],
                        "chunk_index": int(
                            chunk["chunk_index"]
                        ),
                        "content": chunk["content"],
                        "source_type": chunk["source_type"],
                        "page_number": int(
                            chunk["page_number"]
                        ),
                        "start_seconds": float(
                            chunk["start_seconds"]
                        ),
                        "end_seconds": float(
                            chunk["end_seconds"]
                        ),
                        "metadata": chunk["metadata"],
                        "dense_vector": dense_vector,
                        "sparse_vector": sparse_vector,
                    }
                )

            await milvus_indexing_service.replace_document_vectors(
                document_id=str(document.id),
                records=records,
            )

            document_metadata.update(
                {
                    "embedding_model": (
                        settings.embedding_model
                    ),
                    "embedding_dimension": (
                        DENSE_VECTOR_DIMENSION
                    ),
                    "indexed_chunk_count": len(records),
                }
            )

            document.extra_metadata = document_metadata
            document.status = "READY"

            task.status = "SUCCESS"
            task.progress = 100
            task.error_message = None

            await db.commit()

            return {
                "document_id": str(document.id),
                "file_name": document.file_name,
                "status": document.status,
                "embedding_model": settings.embedding_model,
                "embedding_dimension": (
                    DENSE_VECTOR_DIMENSION
                ),
                "indexed_chunk_count": len(records),
            }

        except Exception as exc:
            logger.exception(
                "文档向量化或索引失败，document_id=%s",
                document.id,
            )

            if current_stage == "embedding":
                document.status = "EMBEDDING_FAILED"
            else:
                document.status = "INDEXING_FAILED"

            task.status = "FAILED"
            task.error_message = str(exc)[:2000]

            await db.commit()

            raise


document_indexing_service = DocumentIndexingService()
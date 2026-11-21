from pymilvus import MilvusClient
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.services.embedding.bge_m3_service import (
    bge_m3_embedding_service,
)


MILVUS_WRITE_BATCH_SIZE = 32


class MilvusIndexingService:
    def _replace_document_vectors_sync(
        self,
        *,
        document_id: str,
        records: list[dict],
    ) -> None:
        client = MilvusClient(uri=settings.milvus_uri)

        try:
            client.load_collection(
                collection_name=settings.milvus_collection
            )

            client.delete(
                collection_name=settings.milvus_collection,
                filter=f'document_id == "{document_id}"',
            )

            for start in range(
                0,
                len(records),
                MILVUS_WRITE_BATCH_SIZE,
            ):
                batch = records[
                    start:start + MILVUS_WRITE_BATCH_SIZE
                ]

                client.upsert(
                    collection_name=settings.milvus_collection,
                    data=batch,
                )

            client.flush(
                collection_name=settings.milvus_collection
            )

        finally:
            client.close()

    async def replace_document_vectors(
        self,
        *,
        document_id: str,
        records: list[dict],
    ) -> None:
        if not records:
            raise ValueError("不能写入空的向量记录")

        await run_in_threadpool(
            self._replace_document_vectors_sync,
            document_id=document_id,
            records=records,
        )

    def _delete_document_vectors_sync(
        self,
        *,
        document_id: str,
    ) -> None:
        client = MilvusClient(
            uri=settings.milvus_uri
        )

        try:
            client.load_collection(
                collection_name=settings.milvus_collection
            )

            client.delete(
                collection_name=settings.milvus_collection,
                filter=(
                    f'document_id == "{document_id}"'
                ),
            )

            client.flush(
                collection_name=settings.milvus_collection
            )

        finally:
            client.close()

    async def delete_document_vectors(
        self,
        *,
        document_id: str,
    ) -> None:
        await run_in_threadpool(
            self._delete_document_vectors_sync,
            document_id=document_id,
        )

    async def replace_note_vectors(
        self,
        *,
        note_id: str,
        user_id: str,
        knowledge_base_id: str,
        title: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Upsert one semantic vector for a note in the shared collection."""
        normalized_content = content.strip()
        if not normalized_content:
            normalized_content = title.strip()
        if not normalized_content:
            raise ValueError("笔记标题和正文不能同时为空")

        embedding_text = (
            f"标题：{title.strip()}\n"
            f"正文：{normalized_content}"
        )[:12000]
        dense_vectors, sparse_vectors = (
            await bge_m3_embedding_service.encode(
                [embedding_text]
            )
        )

        note_metadata = dict(metadata or {})
        note_metadata.update(
            {
                "note_id": note_id,
                "title": title,
                "file_name": title,
                "source_type": "note",
            }
        )

        await run_in_threadpool(
            self._replace_document_vectors_sync,
            document_id=note_id,
            records=[
                {
                    "id": f"note:{note_id}",
                    "user_id": user_id,
                    "knowledge_base_id": knowledge_base_id,
                    "document_id": note_id,
                    "chunk_index": 0,
                    "content": normalized_content,
                    "source_type": "note",
                    "page_number": -1,
                    "start_seconds": 0.0,
                    "end_seconds": 0.0,
                    "metadata": note_metadata,
                    "dense_vector": dense_vectors[0],
                    "sparse_vector": sparse_vectors[0],
                }
            ],
        )

    async def delete_note_vectors(self, *, note_id: str) -> None:
        """Delete only the note vector identified by note_id."""
        await run_in_threadpool(
            self._delete_note_vectors_sync,
            note_id=note_id,
        )

    @staticmethod
    def _delete_note_vectors_sync(*, note_id: str) -> None:
        client = MilvusClient(uri=settings.milvus_uri)
        try:
            client.load_collection(
                collection_name=settings.milvus_collection
            )
            client.delete(
                collection_name=settings.milvus_collection,
                filter=(
                    f'document_id == "{note_id}" and '
                    'source_type == "note"'
                ),
            )
            client.flush(
                collection_name=settings.milvus_collection
            )
        finally:
            client.close()


milvus_indexing_service = MilvusIndexingService()

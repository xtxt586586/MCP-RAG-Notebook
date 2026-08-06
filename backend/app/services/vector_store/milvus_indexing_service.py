from pymilvus import MilvusClient
from starlette.concurrency import run_in_threadpool

from app.core.config import settings


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

            # Stable chunk IDs make re-indexing idempotent. Delete any stale
            # chunks first in case the new parse produced fewer chunks.
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


milvus_indexing_service = MilvusIndexingService()

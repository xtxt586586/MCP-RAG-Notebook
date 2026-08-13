from typing import Any, Literal

from pymilvus import AnnSearchRequest, MilvusClient, RRFRanker
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.services.embedding.bge_m3_service import (
    bge_m3_embedding_service,
)


SearchMode = Literal["dense", "sparse", "hybrid"]

MILVUS_OUTPUT_FIELDS = [
    "content",
    "document_id",
    "chunk_index",
    "page_number",
    "source_type",
    "start_seconds",
    "end_seconds",
    "metadata",
]


class HybridSearchService:
    @staticmethod
    def _build_filter(
        *,
        user_id: str,
        knowledge_base_id: str,
    ) -> str:
        return (
            f'user_id == "{user_id}" and '
            f'knowledge_base_id == "{knowledge_base_id}"'
        )

    @staticmethod
    def _normalize_results(raw_results: list) -> list[dict[str, Any]]:
        if not raw_results:
            return []

        results: list[dict[str, Any]] = []

        for rank, hit in enumerate(raw_results[0], start=1):
            hit_data = dict(hit)
            entity = hit_data.get("entity") or {}

            if hasattr(entity, "to_dict"):
                entity = entity.to_dict()
            else:
                entity = dict(entity)

            metadata = entity.get("metadata") or {}

            results.append(
                {
                    "rank": rank,
                    "score": float(
                        hit_data.get(
                            "distance",
                            hit_data.get("score", 0.0),
                        )
                    ),
                    "chunk_id": str(hit_data.get("id", "")),
                    "content": entity.get("content", ""),
                    "document_id": entity.get("document_id", ""),
                    "chunk_index": int(entity.get("chunk_index", 0)),
                    "file_name": metadata.get("file_name"),
                    "page_number": int(entity.get("page_number", 0)),
                    "source_type": entity.get("source_type", "text"),
                    "start_seconds": float(
                        entity.get("start_seconds", 0.0)
                    ),
                    "end_seconds": float(
                        entity.get("end_seconds", 0.0)
                    ),
                    "metadata": metadata,
                }
            )

        return results

    def _search_sync(
        self,
        *,
        user_id: str,
        knowledge_base_id: str,
        dense_vector: list[float],
        sparse_vector: dict[int, float],
        mode: SearchMode,
        top_k: int,
    ) -> list[dict[str, Any]]:
        client = MilvusClient(uri=settings.milvus_uri)
        search_filter = self._build_filter(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
        )
        candidate_limit = min(max(top_k * 4, 20), 100)#候选集大小

        dense_search_params = {
            "metric_type": "COSINE",#使用余弦相似度
            "params": {"ef": max(candidate_limit, 64)},
        }
        sparse_search_params = {
            "metric_type": "IP",#使用内积
            "params": {"drop_ratio_search": 0.2},
        }

        try:
            client.load_collection(
                collection_name=settings.milvus_collection
            )

            if mode == "dense":
                raw_results = client.search(
                    collection_name=settings.milvus_collection,
                    data=[dense_vector],
                    anns_field="dense_vector",
                    filter=search_filter,
                    limit=top_k,
                    search_params=dense_search_params,
                    output_fields=MILVUS_OUTPUT_FIELDS,
                )
            elif mode == "sparse":
                raw_results = client.search(
                    collection_name=settings.milvus_collection,
                    data=[sparse_vector],
                    anns_field="sparse_vector",
                    filter=search_filter,
                    limit=top_k,
                    search_params=sparse_search_params,
                    output_fields=MILVUS_OUTPUT_FIELDS,
                )
            else:
                dense_request = AnnSearchRequest(
                    data=[dense_vector],
                    anns_field="dense_vector",
                    param=dense_search_params,
                    limit=candidate_limit,
                    filter=search_filter,
                )
                sparse_request = AnnSearchRequest(
                    data=[sparse_vector],
                    anns_field="sparse_vector",
                    param=sparse_search_params,
                    limit=candidate_limit,
                    filter=search_filter,
                )

                raw_results = client.hybrid_search(
                    collection_name=settings.milvus_collection,
                    reqs=[dense_request, sparse_request],
                    ranker=RRFRanker(k=60),
                    limit=top_k,
                    output_fields=MILVUS_OUTPUT_FIELDS,
                )

            return self._normalize_results(raw_results)
        finally:
            client.close()

    async def search(
        self,
        *,
        user_id: str,
        knowledge_base_id: str,
        query: str,
        mode: SearchMode = "hybrid",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        normalized_query = query.strip()

        if not normalized_query:
            raise ValueError("查询内容不能为空")

        dense_vectors, sparse_vectors = (
            await bge_m3_embedding_service.encode([normalized_query])
        )

        return await run_in_threadpool(
            self._search_sync,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            dense_vector=dense_vectors[0],
            sparse_vector=sparse_vectors[0],
            mode=mode,
            top_k=top_k,
        )


hybrid_search_service = HybridSearchService()

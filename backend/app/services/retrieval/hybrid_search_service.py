import asyncio
import logging
import re
from time import perf_counter
from typing import Any, Literal

from pymilvus import (
    AnnSearchRequest,
    MilvusClient,
    RRFRanker,
)
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.services.embedding.bge_m3_service import (
    bge_m3_embedding_service,
)
from app.services.reranking.bge_reranker_service import (
    bge_reranker_service,
)


logger = logging.getLogger(__name__)

SearchMode = Literal[
    "dense",
    "sparse",
    "hybrid",
]

SearchSource = Literal[
    "documents",
    "notes",
    "all",
]


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
    def _lexical_relevance(query: str, content: str) -> float:
        """Estimate whether a chunk contains the query's key terms."""
        normalized_query = re.sub(r"\s+", "", query)
        normalized_content = re.sub(r"\s+", "", content)
        if len(normalized_query) < 2 or len(normalized_content) < 2:
            return 0.0

        query_terms = {
            normalized_query[index:index + 2]
            for index in range(len(normalized_query) - 1)
            if not normalized_query[index:index + 2].isdigit()
        }
        if not query_terms:
            return 0.0

        matched_terms = sum(
            1 for term in query_terms if term in normalized_content
        )
        if matched_terms < 2:
            return 0.0
        return min(1.0, matched_terms / len(query_terms) * 1.5)

    async def route_score(
        self,
        *,
        user_id: str,
        knowledge_base_id: str,
        query: str,
        dense_vector: list[float] | None = None,
    ) -> float:
        """Return a cosine-similarity score for the best document chunk."""
        started_at = perf_counter()
        embedding_ms = 0.0
        if dense_vector is None:
            embedding_started_at = perf_counter()
            dense_vectors, _ = await bge_m3_embedding_service.encode([query])
            dense_vector = dense_vectors[0]
            embedding_ms = (perf_counter() - embedding_started_at) * 1000
        search_started_at = perf_counter()
        candidates = await run_in_threadpool(
            self._search_sync,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            source="documents",
            dense_vector=dense_vector,
            sparse_vector={},
            mode="dense",
            candidate_limit=12,
        )
        search_ms = (perf_counter() - search_started_at) * 1000
        if not candidates:
            logger.info(
                "RAG 检索阶段耗时 phase=route_score embedding_ms=%.2f "
                "milvus_ms=%.2f total_ms=%.2f candidates=0",
                embedding_ms,
                search_ms,
                (perf_counter() - started_at) * 1000,
            )
            return 0.0

        # Milvus returns cosine similarity for COSINE: larger is more similar.
        # The SDK names this field "distance" even for similarity metrics.
        similarity = float(candidates[0].get("score", 0.0))
        semantic_score = max(0.0, min(1.0, similarity))
        lexical_overlap = max(
            (
                self._lexical_relevance(
                    query,
                    str(candidate.get("content", "")),
                )
                for candidate in candidates
            ),
            default=0.0,
        )
        lexical_score = lexical_overlap
        route_score = max(semantic_score, lexical_score)
        # Scores just above the threshold are often weak semantic matches
        # (for example, a generic weather question against an unrelated
        # chunk). Require a small margin unless lexical evidence is present.
        if (
            lexical_score < settings.rag_min_relevance_score
            and semantic_score < (
                settings.rag_min_relevance_score
                + settings.rag_route_score_margin
            )
        ):
            route_score = settings.rag_min_relevance_score
        logger.info(
            "RAG 检索阶段耗时 phase=route_score embedding_ms=%.2f "
            "milvus_ms=%.2f total_ms=%.2f candidates=%d "
            "semantic_score=%.3f lexical_score=%.3f",
            embedding_ms,
            search_ms,
            (perf_counter() - started_at) * 1000,
            len(candidates),
            semantic_score,
            lexical_score,
        )
        return route_score

    @staticmethod
    def _build_filter(
        *,
        user_id: str,
        knowledge_base_id: str,
        source: SearchSource = "documents",
    ) -> str:
        filter_expression = (
            f'user_id == "{user_id}" and '
            f'knowledge_base_id == "{knowledge_base_id}"'
        )
        if source == "notes":
            return f'{filter_expression} and source_type == "note"'
        if source == "documents":
            return f'{filter_expression} and source_type != "note"'
        return filter_expression

    @staticmethod
    def _normalize_results(
        raw_results: list,
    ) -> list[dict[str, Any]]:
        if not raw_results:
            return []

        results: list[dict[str, Any]] = []

        for rank, hit in enumerate(
            raw_results[0],
            start=1,
        ):
            hit_data = dict(hit)
            entity = hit_data.get(
                "entity"
            ) or {}

            if hasattr(entity, "to_dict"):
                entity = entity.to_dict()
            else:
                entity = dict(entity)

            metadata = entity.get(
                "metadata"
            ) or {}

            results.append(
                {
                    "rank": rank,
                    "score": float(
                        hit_data.get(
                            "distance",
                            hit_data.get(
                                "score",
                                0.0,
                            ),
                        )
                    ),
                    "chunk_id": str(
                        hit_data.get(
                            "id",
                            "",
                        )
                    ),
                    "content": entity.get(
                        "content",
                        "",
                    ),
                    "document_id": entity.get(
                        "document_id",
                        "",
                    ),
                    "chunk_index": int(
                        entity.get(
                            "chunk_index",
                            0,
                        )
                    ),
                    "file_name": metadata.get(
                        "file_name"
                    ),
                    "page_number": int(
                        entity.get(
                            "page_number",
                            0,
                        )
                    ),
                    "source_type": entity.get(
                        "source_type",
                        "text",
                    ),
                    "start_seconds": float(
                        entity.get(
                            "start_seconds",
                            0.0,
                        )
                    ),
                    "end_seconds": float(
                        entity.get(
                            "end_seconds",
                            0.0,
                        )
                    ),
                    "metadata": metadata,
                }
            )

        return results

    @staticmethod
    def _set_final_ranks(
        results: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        final_results: list[dict[str, Any]] = []

        for rank, result in enumerate(
            results[:top_k],
            start=1,
        ):
            item = dict(result)
            item["rank"] = rank
            final_results.append(item)

        return final_results

    def _search_sync(
        self,
        *,
        user_id: str,
        knowledge_base_id: str,
        source: SearchSource,
        dense_vector: list[float],
        sparse_vector: dict[int, float],
        mode: SearchMode,
        candidate_limit: int,
    ) -> list[dict[str, Any]]:
        client = MilvusClient(
            uri=settings.milvus_uri
        )

        search_filter = self._build_filter(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            source=source,
        )

        dense_search_params = {
            "metric_type": "COSINE",
            "params": {
                "ef": max(candidate_limit, 64),
            },
        }

        sparse_search_params = {
            "metric_type": "IP",
            "params": {
                "drop_ratio_search": 0.2,
            },
        }

        try:
            client.load_collection(
                collection_name=settings.milvus_collection
            )

            if mode == "dense":
                raw_results = client.search(
                    collection_name=(
                        settings.milvus_collection
                    ),
                    data=[dense_vector],
                    anns_field="dense_vector",
                    filter=search_filter,
                    limit=candidate_limit,
                    search_params=dense_search_params,
                    output_fields=MILVUS_OUTPUT_FIELDS,
                )

            elif mode == "sparse":
                raw_results = client.search(
                    collection_name=(
                        settings.milvus_collection
                    ),
                    data=[sparse_vector],
                    anns_field="sparse_vector",
                    filter=search_filter,
                    limit=candidate_limit,
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
                    collection_name=(
                        settings.milvus_collection
                    ),
                    reqs=[
                        dense_request,
                        sparse_request,
                    ],
                    ranker=RRFRanker(k=60),
                    limit=candidate_limit,
                    output_fields=MILVUS_OUTPUT_FIELDS,
                )

            return self._normalize_results(
                raw_results
            )

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
        source: SearchSource = "documents",
        dense_vector: list[float] | None = None,
        sparse_vector: dict[int, float] | None = None,
    ) -> list[dict[str, Any]]:
        started_at = perf_counter()
        normalized_query = query.strip()

        if not normalized_query:
            raise ValueError(
                "查询内容不能为空"
            )

        if not 1 <= top_k <= 20:
            raise ValueError(
                "top_k 必须在 1 到 20 之间"
            )

        embedding_ms = 0.0
        if dense_vector is None or sparse_vector is None:
            embedding_started_at = perf_counter()
            dense_vectors, sparse_vectors = (
                await bge_m3_embedding_service.encode(
                    [normalized_query]
                )
            )
            dense_vector = dense_vectors[0]
            sparse_vector = sparse_vectors[0]
            embedding_ms = (perf_counter() - embedding_started_at) * 1000

        candidate_limit = min(
            max(top_k + 1, 6),
            50,
        )

        milvus_started_at = perf_counter()
        candidates = await run_in_threadpool(
            self._search_sync,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            source=source,
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            mode=mode,
            candidate_limit=candidate_limit,
        )
        milvus_ms = (perf_counter() - milvus_started_at) * 1000

        if not candidates:
            logger.info(
                "RAG 检索阶段耗时 phase=search mode=%s source=%s "
                "embedding_ms=%.2f milvus_ms=%.2f reranker_ms=0 "
                "total_ms=%.2f candidates=0",
                mode,
                source,
                embedding_ms,
                milvus_ms,
                (perf_counter() - started_at) * 1000,
            )
            return []

        if not settings.reranker_enabled:
            logger.info(
                "RAG 检索阶段耗时 phase=search mode=%s source=%s "
                "embedding_ms=%.2f milvus_ms=%.2f reranker_ms=0 "
                "total_ms=%.2f candidates=%d reranker=disabled",
                mode,
                source,
                embedding_ms,
                milvus_ms,
                (perf_counter() - started_at) * 1000,
                len(candidates),
            )
            return self._set_final_ranks(
                candidates,
                top_k,
            )

        reranker_started_at = perf_counter()
        try:
            reranked_results = await asyncio.wait_for(
                bge_reranker_service.rerank(
                    query=normalized_query,
                    results=candidates,
                ),
                timeout=settings.reranker_timeout_seconds,
            )

            reranker_ms = (perf_counter() - reranker_started_at) * 1000
            logger.info(
                "RAG 检索阶段耗时 phase=search mode=%s source=%s "
                "embedding_ms=%.2f milvus_ms=%.2f reranker_ms=%.2f "
                "total_ms=%.2f candidates=%d",
                mode,
                source,
                embedding_ms,
                milvus_ms,
                reranker_ms,
                (perf_counter() - started_at) * 1000,
                len(candidates),
            )
            return self._set_final_ranks(
                reranked_results,
                top_k,
            )

        except asyncio.TimeoutError:
            reranker_ms = (perf_counter() - reranker_started_at) * 1000
            logger.warning(
                "Reranker 超时，回退到 Milvus 排序 timeout_seconds=%.2f "
                "elapsed_ms=%.2f candidates=%d",
                settings.reranker_timeout_seconds,
                reranker_ms,
                len(candidates),
            )
            return self._set_final_ranks(candidates, top_k)

        except Exception:
            reranker_ms = (perf_counter() - reranker_started_at) * 1000
            logger.exception(
                "Reranker 排序失败，回退到 Milvus 排序"
            )
            logger.info(
                "RAG 检索阶段耗时 phase=search mode=%s source=%s "
                "embedding_ms=%.2f milvus_ms=%.2f reranker_ms=%.2f "
                "total_ms=%.2f candidates=%d reranker=failed",
                mode,
                source,
                embedding_ms,
                milvus_ms,
                reranker_ms,
                (perf_counter() - started_at) * 1000,
                len(candidates),
            )

            return self._set_final_ranks(
                candidates,
                top_k,
            )


hybrid_search_service = HybridSearchService()

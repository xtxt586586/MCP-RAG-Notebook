import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any

from FlagEmbedding import FlagReranker
from huggingface_hub import snapshot_download
from starlette.concurrency import run_in_threadpool

from app.core.config import settings


logger = logging.getLogger(__name__)


class BGERerankerService:
    def __init__(self) -> None:
        self._model: FlagReranker | None = None
        self._model_lock = Lock()

    @staticmethod
    def _resolve_model_path() -> str:
        configured_model = settings.reranker_model

        local_path = Path(configured_model)

        if local_path.exists():
            return str(local_path.resolve())

        if settings.embedding_offline:
            os.environ["HF_HUB_OFFLINE"] = "1"

            return snapshot_download(
                repo_id=configured_model,
                local_files_only=True,
            )

        return configured_model

    def _get_model(self) -> FlagReranker:
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is None:
                model_path = self._resolve_model_path()

                logger.info(
                    "正在加载 Reranker 模型：%s",
                    model_path,
                )

                self._model = FlagReranker(
                    model_path,
                    use_fp16=False,
                )

                logger.info(
                    "Reranker 模型加载完成"
                )

        return self._model

    def _rerank_sync(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not results:
            return []

        model = self._get_model()

        pairs = [
            [
                query,
                str(result.get("content", "")),
            ]
            for result in results
        ]

        scores = model.compute_score(
            pairs,
            normalize=True,
        )

        if isinstance(scores, float):
            scores = [scores]

        reranked_results: list[dict[str, Any]] = []

        for result, score in zip(
            results,
            scores,
            strict=False,
        ):
            item = dict(result)

            item["retrieval_score"] = item.get(
                "score",
                0.0,
            )

            item["rerank_score"] = float(score)
            item["score"] = float(score)

            reranked_results.append(item)

        reranked_results.sort(
            key=lambda item: item["rerank_score"],
            reverse=True,
        )

        return reranked_results

    async def rerank(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized_query = query.strip()

        if not normalized_query:
            raise ValueError("查询内容不能为空")

        return await run_in_threadpool(
            self._rerank_sync,
            query=normalized_query,
            results=results,
        )


bge_reranker_service = BGERerankerService()
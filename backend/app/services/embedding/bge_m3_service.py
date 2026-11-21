import logging
import os
from pathlib import Path
from threading import Lock

from huggingface_hub import snapshot_download
from starlette.concurrency import run_in_threadpool

from app.core.config import settings


if settings.embedding_offline:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

from FlagEmbedding import BGEM3FlagModel  # noqa: E402


logger = logging.getLogger(__name__)

DENSE_VECTOR_DIMENSION = 1024


class BGEM3EmbeddingService:
    def __init__(self) -> None:
        self._model: BGEM3FlagModel | None = None
        self._model_lock = Lock()

    @staticmethod
    def _resolve_model_path() -> str:
        configured_model = settings.embedding_model

        local_path = Path(configured_model)
        if local_path.exists():
            return str(local_path.resolve())

        # FlagEmbedding otherwise downloads the whole Hub repository, including
        # unrelated ONNX exports and images, on a fresh machine. Keep the
        # tokenizer, PyTorch weights and sparse/ColBERT projection weights.
        return snapshot_download(
            repo_id=configured_model,
            local_files_only=settings.embedding_offline,
            ignore_patterns=["onnx/*", "imgs/*", "*.jpg", "*.png", "*.webp"],
        )

    def _get_model(self) -> BGEM3FlagModel:
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is None:
                model_path = self._resolve_model_path()

                logger.info(
                    "正在加载 Embedding 模型：%s",
                    model_path,
                )

                self._model = BGEM3FlagModel(
                    model_path,
                    use_fp16=False,
                )

                logger.info("Embedding 模型加载完成")

        return self._model

    @staticmethod
    def _convert_dense_vector(vector) -> list[float]:
        if hasattr(vector, "tolist"):
            vector = vector.tolist()

        return [
            float(value)
            for value in vector
        ]

    @staticmethod
    def _convert_sparse_vector(
        lexical_weights: dict,
    ) -> dict[int, float]:
        sparse_vector = {
            int(token_id): float(weight)
            for token_id, weight in lexical_weights.items()
            if float(weight) != 0.0
        }

        if not sparse_vector:
            raise ValueError("模型生成了空的稀疏向量")

        return sparse_vector

    def _encode_sync(
        self,
        texts: list[str],
    ) -> tuple[list[list[float]], list[dict[int, float]]]:
        if not texts:
            raise ValueError("待向量化的文本不能为空")

        model = self._get_model()

        output = model.encode(
            texts,
            batch_size=settings.embedding_batch_size,
            max_length=settings.embedding_max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )

        dense_vectors = [
            self._convert_dense_vector(vector)
            for vector in output["dense_vecs"]
        ]

        sparse_vectors = [
            self._convert_sparse_vector(weights)
            for weights in output["lexical_weights"]
        ]

        for vector in dense_vectors:
            if len(vector) != DENSE_VECTOR_DIMENSION:
                raise ValueError(
                    "稠密向量维度错误："
                    f"期望 {DENSE_VECTOR_DIMENSION}，"
                    f"实际 {len(vector)}"
                )

        if len(dense_vectors) != len(texts):
            raise ValueError("稠密向量数量与文本数量不一致")

        if len(sparse_vectors) != len(texts):
            raise ValueError("稀疏向量数量与文本数量不一致")

        return dense_vectors, sparse_vectors

    async def encode(
        self,
        texts: list[str],
    ) -> tuple[list[list[float]], list[dict[int, float]]]:
        return await run_in_threadpool(
            self._encode_sync,
            texts,
        )


bge_m3_embedding_service = BGEM3EmbeddingService()

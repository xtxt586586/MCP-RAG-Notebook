"""Download and exercise the models used by the knowledge-base demo."""
import argparse
import math
import os


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true",
        help="Require locally cached models; do not contact Hugging Face",
    )
    parser.add_argument(
        "--reranker", action="store_true",
        help="Also prepare and exercise the optional reranker",
    )
    args = parser.parse_args()

    # Set before importing settings and FlagEmbedding. This lets one-off
    # verification run offline without changing the running services' .env.
    if args.offline:
        os.environ["EMBEDDING_OFFLINE"] = "true"
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    from app.services.embedding.bge_m3_service import bge_m3_embedding_service

    dense, sparse = bge_m3_embedding_service._encode_sync(["模型准备检查"])
    print(f"Embedding OK: dimension={len(dense[0])}, sparse_terms={len(sparse[0])}", flush=True)

    if args.reranker:
        from app.services.reranking.bge_reranker_service import bge_reranker_service

        result = bge_reranker_service._rerank_sync(
            query="模型准备检查", results=[{"content": "模型准备检查", "score": 0.0}]
        )
        if len(result) != 1 or not math.isfinite(result[0]["rerank_score"]):
            raise RuntimeError("Reranker did not return a finite score")
        print("Reranker OK", flush=True)


if __name__ == "__main__":
    main()

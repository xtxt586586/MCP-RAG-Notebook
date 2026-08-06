import asyncio
import math

from app.services.embedding.bge_m3_service import (
    bge_m3_embedding_service,
)


def cosine_similarity(
    vector_a: list[float],
    vector_b: list[float],
) -> float:
    dot_product = sum(
        a * b
        for a, b in zip(vector_a, vector_b)
    )

    norm_a = math.sqrt(
        sum(value * value for value in vector_a)
    )

    norm_b = math.sqrt(
        sum(value * value for value in vector_b)
    )

    return dot_product / (norm_a * norm_b)


async def main() -> None:
    texts = [
        "Milvus 是一个向量数据库。",
        "向量数据库可以保存和检索文本向量。",
        "今天天气非常晴朗。",
    ]

    dense_vectors, sparse_vectors = (
        await bge_m3_embedding_service.encode(texts)
    )

    print("文本数量：", len(texts))
    print("稠密向量数量：", len(dense_vectors))
    print("稠密向量维度：", len(dense_vectors[0]))
    print("第一个稀疏向量非零元素数量：", len(sparse_vectors[0]))

    related_score = cosine_similarity(
        dense_vectors[0],
        dense_vectors[1],
    )

    unrelated_score = cosine_similarity(
        dense_vectors[0],
        dense_vectors[2],
    )

    print("相关文本相似度：", related_score)
    print("不相关文本相似度：", unrelated_score)

    if related_score <= unrelated_score:
        raise RuntimeError("Embedding 相似度测试没有通过")

    print("bge-m3 Embedding 测试通过")


if __name__ == "__main__":
    asyncio.run(main())
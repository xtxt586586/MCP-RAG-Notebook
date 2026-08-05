from pymilvus import MilvusClient

from app.core.config import settings


def create_dense_vector(first_value: float) -> list[float]:
    vector = [0.0] * 1024
    vector[0] = first_value
    vector[1] = 1.0 - first_value
    return vector


def test_milvus() -> None:
    client = MilvusClient(uri=settings.milvus_uri)
    collection_name = settings.milvus_collection

    test_ids = [
        "test-chunk-1",
        "test-chunk-2",
    ]

    test_data = [
        {
            "id": "test-chunk-1",
            "user_id": "test-user",
            "knowledge_base_id": "test-kb",
            "document_id": "test-document",
            "chunk_index": 0,
            "content": "Milvus 是一个面向人工智能应用的向量数据库。",
            "source_type": "text",
            "page_number": -1,
            "start_seconds": -1.0,
            "end_seconds": -1.0,
            "metadata": {
                "file_name": "milvus-test.txt",
            },
            "dense_vector": create_dense_vector(1.0),
            "sparse_vector": {
                0: 1.0,
                10: 0.5,
            },
        },
        {
            "id": "test-chunk-2",
            "user_id": "test-user",
            "knowledge_base_id": "test-kb",
            "document_id": "test-document",
            "chunk_index": 1,
            "content": "PostgreSQL 用于保存用户和文档元数据。",
            "source_type": "text",
            "page_number": -1,
            "start_seconds": -1.0,
            "end_seconds": -1.0,
            "metadata": {
                "file_name": "postgres-test.txt",
            },
            "dense_vector": create_dense_vector(0.0),
            "sparse_vector": {
                1: 1.0,
                20: 0.5,
            },
        },
    ]

    try:
        client.upsert(
            collection_name=collection_name,
            data=test_data,
        )

        client.flush(collection_name=collection_name)

        print("测试数据写入成功")

        results = client.search(
            collection_name=collection_name,
            data=[create_dense_vector(1.0)],
            anns_field="dense_vector",
            filter=(
                'user_id == "test-user" and '
                'knowledge_base_id == "test-kb"'
            ),
            limit=2,
            output_fields=[
                "content",
                "document_id",
                "chunk_index",
                "metadata",
            ],
            search_params={
                "metric_type": "COSINE",
                "params": {
                    "ef": 64,
                },
            },
        )

        print("检索结果：")

        for hit in results[0]:
            print(
                "ID:",
                hit["id"],
                "相似度:",
                hit["distance"],
                "内容:",
                hit["entity"]["content"],
            )

    finally:
        client.delete(
            collection_name=collection_name,
            ids=test_ids,
        )
        client.close()

        print("测试数据已清理")


if __name__ == "__main__":
    test_milvus()
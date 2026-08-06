import argparse

from pymilvus import MilvusClient

from app.core.config import settings


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "document_id",
        help="需要检查的文档 UUID",
    )

    args = parser.parse_args()

    client = MilvusClient(
        uri=settings.milvus_uri
    )

    try:
        results = client.query(
            collection_name=settings.milvus_collection,
            filter=(
                f'document_id == "{args.document_id}"'
            ),
            output_fields=[
                "id",
                "chunk_index",
                "content",
                "page_number",
                "source_type",
            ],
            limit=100,
        )

        print("查询到的向量记录数量：", len(results))

        for result in results[:5]:
            print("-" * 60)
            print("ID：", result["id"])
            print("分块序号：", result["chunk_index"])
            print("页码：", result["page_number"])
            print("来源类型：", result["source_type"])
            print("内容：", result["content"][:200])

    finally:
        client.close()


if __name__ == "__main__":
    main()
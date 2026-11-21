import argparse
import asyncio
from typing import Any

from minio.error import S3Error
from pymilvus import MilvusClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import Document
from app.services.storage.minio_service import (
    minio_storage,
)


async def object_exists(
    object_name: str,
) -> bool:
    try:
        await asyncio.to_thread(
            minio_storage.client.stat_object,
            minio_storage.bucket_name,
            object_name,
        )
        return True

    except S3Error:
        return False

    except Exception as exc:
        print(
            f"MinIO 检查失败：{object_name}，"
            f"{exc}"
        )
        return False


def get_milvus_vector_count(
    document_id: str,
) -> int:
    client = MilvusClient(
        uri=settings.milvus_uri
    )

    try:
        results = client.query(
            collection_name=settings.milvus_collection,
            filter=(
                f'document_id == "{document_id}"'
            ),
            output_fields=["id"],
            limit=10000,
        )

        return len(results)

    finally:
        client.close()


def get_expected_objects(
    document: Document,
) -> list[str]:
    metadata: dict[str, Any] = (
        document.extra_metadata or {}
    )

    object_names = [
        document.object_name,
    ]

    for key in (
            "parsed_text_object_name",
            "chunks_object_name",
            "raw_text_object_name",
    ):
        object_name = metadata.get(key)

        if object_name:
            object_names.append(
                str(object_name)
            )

    return list(dict.fromkeys(object_names))


async def check_document(
    document: Document,
) -> dict[str, Any]:
    object_names = get_expected_objects(
        document
    )

    object_results: dict[str, bool] = {}

    for object_name in object_names:
        object_results[object_name] = (
            await object_exists(object_name)
        )

    vector_count = await asyncio.to_thread(
        get_milvus_vector_count,
        str(document.id),
    )

    missing_objects = [
        object_name
        for object_name, exists
        in object_results.items()
        if not exists
    ]

    status = document.status

    problems: list[str] = []

    if status in {
        "UPLOADED",
        "PARSING",
        "PARSED",
        "EMBEDDING",
        "INDEXING",
        "READY",
    } and missing_objects:
        problems.append(
            "MinIO 对象缺失"
        )

    if status == "READY" and vector_count == 0:
        problems.append(
            "READY 文档没有 Milvus 向量"
        )

    if status == "READY":
        metadata = (
            document.extra_metadata or {}
        )

        if metadata.get(
                "raw_text_preserved"
        ) and not metadata.get(
            "raw_text_object_name"
        ):
            problems.append(
                "标记了 raw_text_preserved，"
                "但缺少 raw_text_object_name"
            )

        if not metadata.get(
            "chunks_object_name"
        ):
            problems.append(
                "缺少 chunks_object_name"
            )

    return {
        "document_id": str(document.id),
        "file_name": document.file_name,
        "status": status,
        "object_count": len(object_names),
        "missing_objects": missing_objects,
        "vector_count": vector_count,
        "problems": problems,
        "consistent": not problems,
    }


async def load_documents(
    document_id: str | None,
) -> list[Document]:
    async with AsyncSessionLocal() as db:
        statement = select(Document).order_by(
            Document.created_at.desc()
        )

        if document_id:
            statement = statement.where(
                Document.id == document_id
            )

        result = await db.execute(statement)

        return list(result.scalars().all())


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "检查 PostgreSQL、MinIO、Milvus "
            "之间的文档一致性"
        )
    )

    parser.add_argument(
        "--document-id",
        help="只检查指定文档 UUID",
    )

    args = parser.parse_args()

    documents = await load_documents(
        args.document_id
    )

    if not documents:
        print("没有找到需要检查的文档")
        return 1

    consistent_count = 0

    for document in documents:
        result = await check_document(
            document
        )

        state = (
            "CONSISTENT"
            if result["consistent"]
            else "INCONSISTENT"
        )

        print("-" * 72)
        print("文档：", result["file_name"])
        print("ID：", result["document_id"])
        print("状态：", result["status"])
        print(
            "MinIO 对象数量：",
            result["object_count"],
        )
        print(
            "Milvus 向量数量：",
            result["vector_count"],
        )
        print("检查结果：", state)

        if result["missing_objects"]:
            print("缺失对象：")
            for object_name in (
                result["missing_objects"]
            ):
                print("  -", object_name)

        if result["problems"]:
            print("问题：")
            for problem in result["problems"]:
                print("  -", problem)

        if result["consistent"]:
            consistent_count += 1

    print("-" * 72)
    print(
        f"检查完成：{consistent_count}/"
        f"{len(documents)} 个文档一致"
    )

    return (
        0
        if consistent_count == len(documents)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(main())
    )
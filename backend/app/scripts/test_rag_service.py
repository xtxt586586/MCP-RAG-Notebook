import asyncio
import json

from app.services.rag.rag_service import (
    rag_service,
)


USER_ID = (
    "00000000-0000-0000-0000-000000000001"
)

KNOWLEDGE_BASE_ID = (
    "00000000-0000-0000-0000-000000000101"
)


async def main() -> None:
    result = await rag_service.answer(
        user_id=USER_ID,
        knowledge_base_id=KNOWLEDGE_BASE_ID,
        query="LangChain 在资料中解决了什么问题？",
        top_k=2,
    )

    print("\nRAG 回答：")
    print(result["answer"])

    print("\n引用来源：")
    print(
        json.dumps(
            result["sources"],
            ensure_ascii=False,
            indent=2,
        )
    )

    if not result["answer"].strip():
        raise AssertionError("RAG 回答为空")

    if not result["sources"]:
        raise AssertionError(
            "RAG 没有返回引用来源"
        )

    source_contains_langchain = any(
        "LangChain" in source["excerpt"]
        for source in result["sources"]
    )

    if not source_contains_langchain:
        raise AssertionError(
            "检索结果中没有找到 LangChain 相关资料"
        )

    has_citation = any(
        source["citation"] in result["answer"]
        for source in result["sources"]
    )

    if not has_citation:
        raise AssertionError(
            "DeepSeek 回答中没有使用引用标记"
        )

    print("\n3E-B RAG 服务测试通过")


if __name__ == "__main__":
    asyncio.run(main())
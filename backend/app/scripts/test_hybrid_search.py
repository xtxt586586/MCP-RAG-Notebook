import argparse
import asyncio

from app.services.retrieval.hybrid_search_service import (
    hybrid_search_service,
)


DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_KNOWLEDGE_BASE_ID = "00000000-0000-0000-0000-000000000101"
ISOLATION_TEST_KNOWLEDGE_BASE_ID = (
    "00000000-0000-0000-0000-000000000999"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test BGE-M3 dense, sparse, and hybrid retrieval."
    )
    parser.add_argument(
        "--user-id",
        default=DEFAULT_USER_ID,
    )
    parser.add_argument(
        "--knowledge-base-id",
        default=DEFAULT_KNOWLEDGE_BASE_ID,
    )
    parser.add_argument(
        "--query",
        default="LangChain 解决了什么问题？",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=2,
    )
    return parser.parse_args()


async def run_test(args: argparse.Namespace) -> None:
    mode_results: dict[str, list[dict]] = {}

    for mode in ("dense", "sparse", "hybrid"):
        results = await hybrid_search_service.search(
            user_id=args.user_id,
            knowledge_base_id=args.knowledge_base_id,
            query=args.query,
            mode=mode,
            top_k=args.top_k,
        )
        mode_results[mode] = results

        if not results:
            raise AssertionError(f"{mode} 检索没有返回结果")

        print(f"\n[{mode.upper()}] 共 {len(results)} 条")
        for item in results:
            preview = item["content"].replace("\n", " ")[:100]
            print(
                f"#{item['rank']} score={item['score']:.6f} "
                f"document={item['document_id']} "
                f"file={item['file_name']}\n  {preview}"
            )

    hybrid_results_again = await hybrid_search_service.search(
        user_id=args.user_id,
        knowledge_base_id=args.knowledge_base_id,
        query=args.query,
        mode="hybrid",
        top_k=args.top_k,
    )

    first_ids = [item["chunk_id"] for item in mode_results["hybrid"]]
    second_ids = [item["chunk_id"] for item in hybrid_results_again]
    if first_ids != second_ids:
        raise AssertionError("相同查询的混合检索排序不稳定")

    isolated_results = await hybrid_search_service.search(
        user_id=args.user_id,
        knowledge_base_id=ISOLATION_TEST_KNOWLEDGE_BASE_ID,
        query=args.query,
        mode="hybrid",
        top_k=args.top_k,
    )
    if isolated_results:
        raise AssertionError("知识库过滤失败，检索到了其他知识库的数据")

    print("\n3D 混合检索测试通过")
    print("- Dense 检索：通过")
    print("- Sparse 检索：通过")
    print("- RRF Hybrid 检索：通过")
    print("- 重复查询稳定性：通过")
    print("- 知识库隔离：通过")


if __name__ == "__main__":
    asyncio.run(run_test(parse_args()))

import asyncio
import json
import sys

from app.services.agent.mcp_agent_service import (
    mcp_agent_service,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def main() -> None:
    result = await mcp_agent_service.answer(
        user_id=(
            "00000000-0000-0000-"
            "0000-000000000001"
        ),
        knowledge_base_id=(
            "00000000-0000-0000-"
            "0000-000000000101"
        ),
        question=(
            "请先使用知识库检索工具查找"
            " LangChain 相关资料，然后根据"
            "检索结果回答它在资料中解决了"
            "什么问题，并说明引用文件。"
        ),
    )

    print("\nAgent 回答：")
    print(result["answer"])

    print("\n工具调用过程：")
    print(
        json.dumps(
            result["tool_steps"],
            ensure_ascii=False,
            indent=2,
        )
    )

    if not result["answer"].strip():
        raise AssertionError(
            "Agent 回答为空"
        )

    if not result["tool_steps"]:
        raise AssertionError(
            "DeepSeek 没有调用 MCP 工具"
        )

    used_search = any(
        step["server_name"]
        == "rag_notebook"
        and step["tool_name"]
        == "search_knowledge_base"
        for step in result["tool_steps"]
    )

    if not used_search:
        raise AssertionError(
            "没有调用知识库检索工具"
        )

    if any(
        step["is_error"]
        for step in result["tool_steps"]
    ):
        raise AssertionError(
            "存在执行失败的 MCP 工具"
        )

    print("\n4D-B MCP Agent 测试通过")


if __name__ == "__main__":
    asyncio.run(main())
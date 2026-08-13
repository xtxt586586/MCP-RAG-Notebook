import asyncio

from app.services.mcp.tool_catalog import (
    mcp_tool_catalog,
)


async def main() -> None:
    tools, mapping = (
        await mcp_tool_catalog.build_catalog()
    )

    print("DeepSeek 可用工具：")

    for tool in tools:
        print(
            "-",
            tool["function"]["name"],
        )

    print("\n工具映射：")
    print(mapping)

    expected = {
        "rag_notebook__search_knowledge_base",
        "filesystem__read_text_file",
        "fetch__fetch",
    }

    actual = {
        tool["function"]["name"]
        for tool in tools
    }

    if not expected.issubset(actual):
        raise AssertionError(
            "MCP Agent 工具目录不完整"
        )

    print("\n4D-A 工具目录测试通过")


if __name__ == "__main__":
    asyncio.run(main())
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import (
    StdioServerParameters,
    stdio_client,
)


USER_ID = (
    "5c431a5b-b480-4c91-8741-f21aa7d2f7c7"
)

KNOWLEDGE_BASE_ID = (
    "738beb50-38f9-4ba9-91a6-18eba9b035f6"
)


def print_tool_result(result) -> None:
    for content in result.content:
        text = getattr(content, "text", None)

        if text:
            print(text)


async def main() -> None:
    server_path = (
        Path(__file__)
        .resolve()
        .with_name("server.py")
    )

    server_parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)],
    )

    async with stdio_client(
        server_parameters
    ) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:
            await session.initialize()

            tools_result = (
                await session.list_tools()
            )

            tool_names = [
                tool.name
                for tool in tools_result.tools
            ]

            print("MCP 工具列表：")
            print(tool_names)

            expected_tools = {
                "backend_health",
                "search_knowledge_base",
                "ask_knowledge_base",
            }

            if not expected_tools.issubset(
                set(tool_names)
            ):
                raise AssertionError(
                    "MCP 工具注册不完整"
                )

            print("\n测试后端健康检查：")

            health_result = (
                await session.call_tool(
                    "backend_health",
                    arguments={},
                )
            )

            print_tool_result(health_result)

            if health_result.isError:
                raise AssertionError(
                    "后端健康检查失败"
                )

            print("\n测试知识库检索：")

            search_result = (
                await session.call_tool(
                    "search_knowledge_base",
                    arguments={
                        "user_id": USER_ID,
                        "knowledge_base_id": (
                            KNOWLEDGE_BASE_ID
                        ),
                        "query": (
                            "LangChain 解决了"
                            "什么问题？"
                        ),
                        "top_k": 2,
                        "mode": "hybrid",
                    },
                )
            )

            print_tool_result(search_result)

            if search_result.isError:
                raise AssertionError(
                    "MCP 知识库检索失败"
                )

            print("\n测试知识库问答：")

            answer_result = (
                await session.call_tool(
                    "ask_knowledge_base",
                    arguments={
                        "user_id": USER_ID,
                        "knowledge_base_id": (
                            KNOWLEDGE_BASE_ID
                        ),
                        "question": (
                            "LangChain 在资料中"
                            "解决了什么问题？"
                        ),
                        "top_k": 2,
                    },
                )
            )

            print_tool_result(answer_result)

            if answer_result.isError:
                raise AssertionError(
                    "MCP 知识库问答失败"
                )

    print("\n第四阶段 4A 测试通过")


if __name__ == "__main__":
    asyncio.run(main())
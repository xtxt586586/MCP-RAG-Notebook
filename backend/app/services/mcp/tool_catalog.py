from typing import Any

from app.core.config import settings
from app.services.mcp.client_manager import (
    mcp_client_manager,
)


class MCPToolCatalog:
    @staticmethod
    def _allowed_tools() -> set[str]:
        return {
            item.strip()
            for item in (
                settings.mcp_agent_allowed_tools
                .split(",")
            )
            if item.strip()
        }

    async def build_catalog(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, tuple[str, str]],
    ]:
        allowed_tools = self._allowed_tools()
        server_names = {
            item.split(":", 1)[0]
            for item in allowed_tools
            if ":" in item
        }

        deepseek_tools: list[dict[str, Any]] = []
        tool_mapping: dict[
            str,
            tuple[str, str],
        ] = {}

        for server_name in sorted(server_names):
            tools = await (
                mcp_client_manager.list_tools(
                    server_name
                )
            )

            for tool in tools:
                tool_name = tool["name"]
                qualified_name = (
                    f"{server_name}:{tool_name}"
                )

                if qualified_name not in allowed_tools:
                    continue

                function_name = (
                    f"{server_name}__{tool_name}"
                )

                deepseek_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "description": (
                                tool.get("description")
                                or qualified_name
                            ),
                            "parameters": tool.get(
                                "inputSchema",
                                {
                                    "type": "object",
                                    "properties": {},
                                },
                            ),
                        },
                    }
                )

                tool_mapping[function_name] = (
                    server_name,
                    tool_name,
                )

        return deepseek_tools, tool_mapping


mcp_tool_catalog = MCPToolCatalog()
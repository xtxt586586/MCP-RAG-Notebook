import asyncio
import logging
from time import perf_counter
from typing import Any

from app.core.config import settings
from app.services.mcp.client_manager import (
    mcp_client_manager,
)


logger = logging.getLogger(__name__)

SERVER_DISCOVERY_TIMEOUT_SECONDS = 3.0
TOOL_CATALOG_CACHE_SECONDS = 60.0
FAILED_SERVER_CACHE_SECONDS = 60.0
MAX_FAILED_SERVER_CACHE_SECONDS = 300.0
PROJECT_OWNED_TOOLS = {
    "rag_notebook:search_knowledge_base",
    "rag_notebook:search_knowledge",
    "rag_notebook:ask_knowledge_base",
}


class MCPToolCatalog:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._cache_lock = asyncio.Lock()
        self._discovery_locks: dict[str, asyncio.Lock] = {}
        self._failure_counts: dict[str, int] = {}

    async def clear_cache(self) -> None:
        """Clear discovered schemas after MCP configuration changes."""
        async with self._cache_lock:
            self._cache.clear()
            self._failure_counts.clear()

    async def _discover_server(
        self,
        server_name: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        async with self._cache_lock:
            discovery_lock = self._discovery_locks.setdefault(
                server_name,
                asyncio.Lock(),
            )

        async with discovery_lock:
            now = perf_counter()
            async with self._cache_lock:
                cached = self._cache.get(server_name)
                if cached is not None and cached[0] > now:
                    logger.debug("使用 MCP 工具目录缓存 server=%s", server_name)
                    return server_name, list(cached[1])

            started_at = perf_counter()
            try:
                tools = await asyncio.wait_for(
                    mcp_client_manager.list_tools(server_name),
                    timeout=SERVER_DISCOVERY_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                async with self._cache_lock:
                    failure_count = self._failure_counts.get(server_name, 0) + 1
                    self._failure_counts[server_name] = failure_count
                    cache_seconds = min(
                        FAILED_SERVER_CACHE_SECONDS * 2 ** (failure_count - 1),
                        MAX_FAILED_SERVER_CACHE_SECONDS,
                    )
                    self._cache[server_name] = (
                        perf_counter() + cache_seconds,
                        [],
                    )
                logger.warning(
                    "跳过不可用 MCP Server：%s error=%s discovery_ms=%.2f cached_for=%.0fs",
                    server_name,
                    str(exc)[:240] or exc.__class__.__name__,
                    (perf_counter() - started_at) * 1000,
                    cache_seconds,
                )
                return server_name, []

            async with self._cache_lock:
                self._failure_counts.pop(server_name, None)
                self._cache[server_name] = (
                    perf_counter() + TOOL_CATALOG_CACHE_SECONDS,
                    list(tools),
                )

            logger.info(
                "MCP 工具发现耗时 server=%s discovery_ms=%.2f tools=%d cached_for=%.0fs",
                server_name,
                (perf_counter() - started_at) * 1000,
                len(tools),
                TOOL_CATALOG_CACHE_SECONDS,
            )
            return server_name, list(tools)

    @staticmethod
    def _allowed_tools() -> set[str]:
        return {
            item.strip()
            for item in (
                settings.mcp_agent_allowed_tools
                .split(",")
            )
            if item.strip() and item.strip() not in PROJECT_OWNED_TOOLS
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

        discovered_servers = await asyncio.gather(
            *(
                self._discover_server(server_name)
                for server_name in sorted(server_names)
            )
        )

        for server_name, tools in discovered_servers:

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

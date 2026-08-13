import asyncio
import ipaddress
import json
import logging
import os
import socket
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp import ClientSession
from mcp.client.stdio import (
    StdioServerParameters,
    stdio_client,
)

from app.core.config import (
    PROJECT_ROOT,
    settings,
)


logger = logging.getLogger(__name__)


SAFE_CHILD_ENV_KEYS = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
}


class MCPClientManager:
    @staticmethod
    def _expand_value(value: str) -> str:
        python_scripts = Path(
            sys.executable
        ).parent

        return (
            value.replace(
                "${PROJECT_ROOT}",
                str(PROJECT_ROOT),
            )
            .replace(
                "${PYTHON_EXECUTABLE}",
                sys.executable,
            )
            .replace(
                "${PYTHON_SCRIPTS}",
                str(python_scripts),
            )
        )

    def _load_config(self) -> dict[str, Any]:
        config_path = Path(
            settings.mcp_servers_config
        )

        if not config_path.exists():
            raise FileNotFoundError(
                "MCP Server 配置文件不存在："
                f"{config_path}"
            )

        with config_path.open(
            "r",
            encoding="utf-8",
        ) as config_file:
            config_data = json.load(config_file)

        servers = config_data.get("servers")

        if not isinstance(servers, dict):
            raise ValueError(
                "MCP 配置必须包含 servers 对象"
            )

        return config_data

    def list_servers(
        self,
    ) -> list[dict[str, Any]]:
        config_data = self._load_config()
        servers = config_data["servers"]

        return [
            {
                "name": server_name,
                "enabled": bool(
                    server_config.get(
                        "enabled",
                        True,
                    )
                ),
                "transport": server_config.get(
                    "transport",
                    "stdio",
                ),
            }
            for server_name, server_config
            in servers.items()
        ]

    def _get_server_config(
        self,
        server_name: str,
    ) -> dict[str, Any]:
        config_data = self._load_config()

        server_config = config_data[
            "servers"
        ].get(server_name)

        if server_config is None:
            raise KeyError(
                f"MCP Server 不存在：{server_name}"
            )

        if not isinstance(server_config, dict):
            raise ValueError(
                f"MCP Server 配置无效："
                f"{server_name}"
            )

        if not server_config.get(
            "enabled",
            True,
        ):
            raise ValueError(
                f"MCP Server 已禁用："
                f"{server_name}"
            )

        transport = server_config.get(
            "transport",
            "stdio",
        )

        if transport != "stdio":
            raise ValueError(
                "当前只支持 stdio，"
                f"实际配置为：{transport}"
            )

        if not server_config.get("command"):
            raise ValueError(
                f"MCP Server 缺少 command："
                f"{server_name}"
            )

        return server_config

    @staticmethod
    def _ensure_tool_allowed(
        *,
        server_name: str,
        tool_name: str,
    ) -> None:
        allowed_tools = {
            item.strip()
            for item in (
                settings.mcp_client_allowed_tools
                .split(",")
            )
            if item.strip()
        }

        qualified_name = (
            f"{server_name}:{tool_name}"
        )

        if qualified_name not in allowed_tools:
            raise PermissionError(
                "不允许调用 MCP 工具："
                f"{qualified_name}"
            )

    @staticmethod
    async def _validate_fetch_url(
        url: str,
    ) -> None:
        parsed = urlparse(url)

        if parsed.scheme not in {
            "http",
            "https",
        }:
            raise ValueError(
                "Fetch 只允许 http 和 https"
            )

        if not parsed.hostname:
            raise ValueError(
                "Fetch URL 缺少主机名"
            )

        if parsed.username or parsed.password:
            raise ValueError(
                "Fetch URL 不允许包含"
                "用户名或密码"
            )

        try:
            port = parsed.port or (
                443
                if parsed.scheme == "https"
                else 80
            )
        except ValueError as exc:
            raise ValueError(
                "Fetch URL 端口无效"
            ) from exc

        loop = asyncio.get_running_loop()

        try:
            addresses = await loop.run_in_executor(
                None,
                lambda: socket.getaddrinfo(
                    parsed.hostname,
                    port,
                    type=socket.SOCK_STREAM,
                ),
            )
        except socket.gaierror as exc:
            raise ValueError(
                "Fetch URL 域名无法解析"
            ) from exc

        if not addresses:
            raise ValueError(
                "Fetch URL 没有可用地址"
            )

        for address_info in addresses:
            address_text = address_info[4][0]

            try:
                address = ipaddress.ip_address(
                    address_text
                )
            except ValueError as exc:
                raise ValueError(
                    "Fetch URL 解析到了"
                    "无效 IP 地址"
                ) from exc

            if not address.is_global:
                raise ValueError(
                    "Fetch 不允许访问本机、"
                    "局域网或保留地址"
                )

    @asynccontextmanager
    async def open_session(
        self,
        server_name: str,
    ) -> AsyncIterator[ClientSession]:
        server_config = (
            self._get_server_config(
                server_name
            )
        )

        command = self._expand_value(
            str(server_config["command"])
        )

        arguments = [
            self._expand_value(str(argument))
            for argument
            in server_config.get("args", [])
        ]

        configured_environment = {
            str(key): self._expand_value(
                str(value)
            )
            for key, value
            in server_config.get(
                "env",
                {},
            ).items()
        }

        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in SAFE_CHILD_ENV_KEYS
        }

        environment.update(
            configured_environment
        )

        server_parameters = (
            StdioServerParameters(
                command=command,
                args=arguments,
                env=environment,
            )
        )

        async with stdio_client(
            server_parameters
        ) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
            ) as session:
                await session.initialize()
                yield session

    async def list_tools(
        self,
        server_name: str,
    ) -> list[dict[str, Any]]:
        async with asyncio.timeout(
            settings.mcp_tool_timeout_seconds
        ):
            async with self.open_session(
                server_name
            ) as session:
                tools_result = (
                    await session.list_tools()
                )

        return [
            tool.model_dump(mode="json")
            for tool in tools_result.tools
        ]

    async def call_tool(
        self,
        *,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        self._ensure_tool_allowed(
            server_name=server_name,
            tool_name=tool_name,
        )

        if (
            server_name == "fetch"
            and tool_name == "fetch"
        ):
            url = arguments.get("url")

            if not isinstance(url, str):
                raise ValueError(
                    "Fetch 工具必须提供 URL"
                )

            await self._validate_fetch_url(url)

        started_at = time.perf_counter()

        try:
            async with asyncio.timeout(
                settings.mcp_tool_timeout_seconds
            ):
                async with self.open_session(
                    server_name
                ) as session:
                    result = (
                        await session.call_tool(
                            tool_name,
                            arguments=arguments,
                        )
                    )

        except Exception:
            duration_ms = (
                time.perf_counter()
                - started_at
            ) * 1000

            logger.exception(
                "MCP 工具调用失败："
                "server=%s tool=%s "
                "duration_ms=%.2f",
                server_name,
                tool_name,
                duration_ms,
            )

            raise

        duration_ms = (
            time.perf_counter()
            - started_at
        ) * 1000

        success = not bool(result.isError)

        logger.info(
            "MCP 工具调用完成："
            "server=%s tool=%s "
            "success=%s duration_ms=%.2f",
            server_name,
            tool_name,
            success,
            duration_ms,
        )

        content = [
            item.model_dump(mode="json")
            for item in result.content
        ]

        structured_content = getattr(
            result,
            "structuredContent",
            None,
        )

        return {
            "server_name": server_name,
            "tool_name": tool_name,
            "is_error": bool(result.isError),
            "content": content,
            "structured_content": (
                structured_content
            ),
        }


mcp_client_manager = MCPClientManager()
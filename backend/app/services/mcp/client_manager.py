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

from uuid import UUID

from app.core.database import AsyncSessionLocal
from app.models import MCPToolCall

from sqlalchemy import select

from app.models import MCPServer


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
    "RAG_BACKEND_URL",
    "RAG_ACCESS_TOKEN",
    "MCP_AUDIT_TOKEN",
    "GITHUB_PERSONAL_ACCESS_TOKEN",
}


class MCPClientManager:
    @staticmethod
    def _is_retryable_exception(exc: Exception) -> bool:
        """Return whether a failed MCP transport call may succeed on retry."""
        if isinstance(
            exc,
            (
                asyncio.TimeoutError,
                ConnectionError,
                OSError,
            ),
        ):
            return True

        message = str(exc).lower()
        transient_markers = (
            "connection closed",
            "connection reset",
            "connection refused",
            "network is unreachable",
            "temporary failure",
            "timed out",
            "broken resource",
            "eof",
        )

        return any(
            marker in message
            for marker in transient_markers
        )

    @staticmethod
    def _is_cancelled_exception(
            exc: BaseException,
    ) -> bool:
        if isinstance(
                exc,
                asyncio.CancelledError,
        ):
            return True

        if isinstance(
                exc,
                BaseExceptionGroup,
        ):
            return any(
                MCPClientManager
                ._is_cancelled_exception(child)
                for child in exc.exceptions
            )

        exception_name = type(exc).__name__

        return exception_name in {
            "BrokenResourceError",
            "ClosedResourceError",
        }


    @staticmethod
    def _is_retryable_tool_error(
            error_message: str,
    ) -> bool:
        message = error_message.lower()

        retryable_markers = (
            "temporary failure",
            "temporary failure in name resolution",
            "fetch failed",
            "connection refused",
            "connection reset",
            "connection error",
            "network is unreachable",
            "timed out",
            "timeout",
            "temporarily rate-limited",
            "rate limit",
            "http 429",
            "http 502",
            "http 503",
            "http 504",
        )

        return any(
            marker in message
            for marker in retryable_markers
        )


    @staticmethod
    def _runtime_project_root() -> Path:
        config_path = Path(
            settings.mcp_servers_config
        ).expanduser().resolve()

        # servers.json 位于 <project_root>/mcp_servers/ 下
        if config_path.parent.name == "mcp_servers":
            return config_path.parent.parent

        return config_path.parent

    @staticmethod
    def _expand_value(value: str) -> str:
        python_scripts = Path(
            sys.executable
        ).parent

        runtime_project_root = (
            MCPClientManager
            ._runtime_project_root()
        )

        return (
            value.replace(
                "${PROJECT_ROOT}",
                str(runtime_project_root),
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

    async def _load_database_server_config(
        self,
        server_name: str,
    ) -> dict[str, Any] | None:
        if not settings.mcp_dynamic_registry_enabled:
            return None
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(MCPServer).where(
                    MCPServer.name == server_name
                )
            )

            server = result.scalar_one_or_none()

        if server is None:
            return None

        return {
            "name": server.name,
            "enabled": server.enabled,
            "transport": server.transport,
            "command": server.command,
            "args": list(
                server.arguments or []
            ),
            "url": server.url,
            "allowed_tools": list(
                server.allowed_tools or []
            ),
            "timeout_seconds": (
                server.timeout_seconds
            ),
            "secret_reference": (
                server.secret_reference
            ),
        }

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

    def _get_json_server_config(
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

    async def _get_server_config(
        self,
        server_name: str,
    ) -> dict[str, Any]:
        database_config = (
            await self
            ._load_database_server_config(
                server_name
            )
        )

        if database_config is not None:
            if not database_config["enabled"]:
                raise ValueError(
                    f"MCP Server 已禁用："
                    f"{server_name}"
                )

            transport = database_config[
                "transport"
            ]

            if transport not in {
                "stdio",
                "streamable_http",
            }:
                raise ValueError(
                    "不支持的 MCP transport："
                    f"{transport}"
                )

            if transport == "stdio":
                if not database_config.get(
                    "command"
                ):
                    raise ValueError(
                        "stdio Server 缺少 command："
                        f"{server_name}"
                    )

            if transport == "streamable_http":
                if not database_config.get(
                    "url"
                ):
                    raise ValueError(
                        "HTTP Server 缺少 url："
                        f"{server_name}"
                    )

            return database_config

        return self._get_json_server_config(
            server_name
        )


    @staticmethod
    def _sanitize_arguments(
        value: Any,
        *,
        depth: int = 0,
    ) -> Any:
        sensitive_keys = {
            "password",
            "token",
            "access_token",
            "refresh_token",
            "api_key",
            "authorization",
            "secret",
        }

        if depth > 4:
            return "[TRUNCATED]"

        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}

            for key, item in value.items():
                key_text = str(key)

                if key_text.lower() in sensitive_keys:
                    sanitized[key_text] = "[REDACTED]"
                else:
                    sanitized[key_text] = (
                        MCPClientManager._sanitize_arguments(
                            item,
                            depth=depth + 1,
                        )
                    )

            return sanitized

        if isinstance(value, list):
            return [
                MCPClientManager._sanitize_arguments(
                    item,
                    depth=depth + 1,
                )
                for item in value[:50]
            ]

        if isinstance(value, str):
            return value[:2000]

        if value is None or isinstance(
            value,
            (bool, int, float),
        ):
            return value

        return str(value)[:2000]

    @staticmethod
    async def _write_audit_log(
        *,
        user_id: str | UUID | None,
        server_name: str,
        tool_name: str,
        status: str,
        duration_ms: int,
        arguments: dict[str, Any],
        result_summary: str | None = None,
        error_message: str | None = None,
    ) -> None:
        try:
            parsed_user_id: UUID | None = None

            if user_id:
                try:
                    parsed_user_id = UUID(
                        str(user_id)
                    )
                except ValueError:
                    parsed_user_id = None

            async with AsyncSessionLocal() as db:
                db.add(
                    MCPToolCall(
                        user_id=parsed_user_id,
                        server_name=server_name,
                        tool_name=tool_name,
                        status=status,
                        duration_ms=duration_ms,
                        safe_arguments=(
                            MCPClientManager
                            ._sanitize_arguments(
                                arguments
                            )
                        ),
                        result_summary=(
                            result_summary[:4000]
                            if result_summary
                            else None
                        ),
                        error_message=(
                            error_message[:4000]
                            if error_message
                            else None
                        ),
                    )
                )

                await db.commit()

        except Exception:
            # 审计失败不能影响 MCP 工具本身的返回结果
            logger.exception(
                "写入 MCP 审计日志失败："
                "server=%s tool=%s",
                server_name,
                tool_name,
            )

    @staticmethod
    async def write_audit_log(
        **kwargs: Any,
    ) -> None:
        """Public adapter for trusted internal audit submissions."""
        await MCPClientManager._write_audit_log(
            **kwargs,
        )

    @staticmethod
    def _ensure_tool_allowed(
            *,
            server_name: str,
            tool_name: str,
            server_config: dict[str, Any],
    ) -> None:
        global_allowed_tools = {
            item.strip()
            for item in (
                settings
                .mcp_client_allowed_tools
                .split(",")
            )
            if item.strip()
        }

        qualified_name = (
            f"{server_name}:{tool_name}"
        )

        if (
                qualified_name
                not in global_allowed_tools
        ):
            raise PermissionError(
                "不允许调用 MCP 工具："
                f"{qualified_name}"
            )

        server_allowed_tools = set(
            server_config.get(
                "allowed_tools",
                [],
            )
        )

        if (
                server_allowed_tools
                and tool_name
                not in server_allowed_tools
        ):
            raise PermissionError(
                "该 MCP Server 未授权工具："
                f"{server_name}:{tool_name}"
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
        access_token: str | None = None,
    ) -> AsyncIterator[ClientSession]:
        server_config = await (
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

        if access_token and server_name in {
            "rag_notebook",
            "multimodal_ingestion",
        }:
            environment["RAG_ACCESS_TOKEN"] = access_token

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
        server_config = await (
            self._get_server_config(
                server_name
            )
        )

        timeout_seconds = float(
            server_config.get(
                "timeout_seconds",
                settings.mcp_tool_timeout_seconds,
            )
        )

        if server_config.get("transport") == "stdio":
            for argument in server_config.get("args", []):
                expanded_argument = self._expand_value(str(argument))
                if expanded_argument.endswith(".py") and not Path(
                    expanded_argument
                ).is_file():
                    raise FileNotFoundError(
                        f"MCP Server {server_name} 脚本不存在："
                        f"{expanded_argument}"
                    )

        async with asyncio.timeout(
                timeout_seconds
        ):
            async with self.open_session(
                    server_name
            ) as session:
                tools_result = (
                    await session.list_tools()
                )

        tools = [
            tool.model_dump(mode="json")
            for tool in tools_result.tools
        ]

        allowed_tools = set(
            server_config.get(
                "allowed_tools",
                [],
            )
        )

        if allowed_tools:
            tools = [
                tool
                for tool in tools
                if tool.get("name")
                   in allowed_tools
            ]

        return tools

    async def call_tool(
            self,
            *,
            server_name: str,
            tool_name: str,
            arguments: dict[str, Any],
            user_id: str | UUID | None = None,
            access_token: str | None = None,
    ) -> dict[str, Any]:
        server_config = await (
            self._get_server_config(
                server_name
            )
        )

        self._ensure_tool_allowed(
            server_name=server_name,
            tool_name=tool_name,
            server_config=server_config,
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

        audit_user_id = user_id

        if audit_user_id is None:
            audit_user_id = arguments.get(
                "user_id"
            )

        started_at = time.perf_counter()

        async def write_cancelled_audit() -> None:
            duration_ms = int(
                (time.perf_counter() - started_at) * 1000
            )

            await self._write_audit_log(
                user_id=audit_user_id,
                server_name=server_name,
                tool_name=tool_name,
                status="CANCELLED",
                duration_ms=duration_ms,
                arguments=arguments,
                error_message="MCP 工具调用已取消",
            )

        timeout_seconds = float(
            server_config.get(
                "timeout_seconds",
                settings.mcp_tool_timeout_seconds,
            )
        )
        retry_attempts = max(
            0,
            int(
                server_config.get(
                    "retry_attempts",
                    settings.mcp_tool_retry_attempts,
                )
            ),
        )
        retry_backoff_seconds = max(
            0.0,
            float(
                server_config.get(
                    "retry_backoff_seconds",
                    settings.mcp_tool_retry_backoff_seconds,
                )
            ),
        )

        for attempt in range(retry_attempts + 1):
            try:
                async with asyncio.timeout(
                    timeout_seconds
                ):
                    async with self.open_session(
                        server_name,
                        access_token=access_token,
                    ) as session:
                        result = await session.call_tool(
                            tool_name,
                            arguments=arguments,
                        )

                        if result.isError:
                            error_parts: list[str] = []
                            for item in result.content:
                                text = getattr(item, "text", None)

                                if text:
                                    error_parts.append(str(text))
                                elif isinstance(item, dict):
                                    item_text = item.get("text")

                                    if item_text:
                                        error_parts.append(
                                            str(item_text)
                                        )

                            tool_error_message = "\n".join(
                                error_parts
                            )[:4000]

                            should_retry = (
                                    attempt < retry_attempts
                                    and self._is_retryable_tool_error(
                                tool_error_message
                            )
                            )

                            if should_retry:
                                delay_seconds = (
                                        retry_backoff_seconds
                                        * (2 ** attempt)
                                )

                                logger.warning(
                                    "MCP 工具返回瞬态错误，将重试："
                                    "server=%s tool=%s attempt=%s/%s "
                                    "delay_seconds=%.2f error=%s",
                                    server_name,
                                    tool_name,
                                    attempt + 1,
                                    retry_attempts + 1,
                                    delay_seconds,
                                    tool_error_message,
                                )

                                try:
                                    await asyncio.sleep(
                                        delay_seconds
                                    )
                                except asyncio.CancelledError:
                                    await write_cancelled_audit()
                                    raise

                                continue

                        break

                break


            except asyncio.CancelledError:
                await write_cancelled_audit()
                raise



            except Exception as exc:
                current_task = asyncio.current_task()

                is_task_cancelling = (
                        current_task is not None
                        and current_task.cancelling() > 0
                )
                if (
                        is_task_cancelling
                        or self._is_cancelled_exception(exc)
                ):
                    await write_cancelled_audit()
                    raise asyncio.CancelledError from exc
                should_retry = (

                        attempt < retry_attempts

                        and self._is_retryable_exception(exc)

                )

                if should_retry:
                    delay_seconds = (
                        retry_backoff_seconds
                        * (2 ** attempt)
                    )

                    logger.warning(
                        "MCP 工具调用失败，将重试："
                        "server=%s tool=%s attempt=%s/%s "
                        "delay_seconds=%.2f error=%s",
                        server_name,
                        tool_name,
                        attempt + 1,
                        retry_attempts + 1,
                        delay_seconds,
                        exc,
                    )

                    try:
                        await asyncio.sleep(delay_seconds)
                    except asyncio.CancelledError:
                        await write_cancelled_audit()
                        raise

                    continue

                duration_ms = int(
                    (
                        time.perf_counter()
                        - started_at
                    )
                    * 1000
                )
                status = (
                    "TIMEOUT"
                    if isinstance(
                        exc,
                        asyncio.TimeoutError,
                    )
                    else "FAILED"
                )
                error_message = (
                    "MCP 工具调用超时"
                    if status == "TIMEOUT"
                    else str(exc)
                )

                await self._write_audit_log(
                    user_id=audit_user_id,
                    server_name=server_name,
                    tool_name=tool_name,
                    status=status,
                    duration_ms=duration_ms,
                    arguments=arguments,
                    error_message=error_message,
                )

                logger.exception(
                    "MCP 工具调用失败："
                    "server=%s tool=%s attempts=%s",
                    server_name,
                    tool_name,
                    attempt + 1,
                )

                raise

        duration_ms = int(
            (
                    time.perf_counter()
                    - started_at
            )
            * 1000
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

        result_texts: list[str] = []

        for item in content:
            if isinstance(item, dict):
                text = item.get("text")

                if text:
                    result_texts.append(
                        str(text)
                    )

        result_summary = "\n".join(
            result_texts
        )[:4000]

        is_error = bool(result.isError)

        await self._write_audit_log(
            user_id=audit_user_id,
            server_name=server_name,
            tool_name=tool_name,
            status=(
                "FAILED"
                if is_error
                else "SUCCESS"
            ),
            duration_ms=duration_ms,
            arguments=arguments,
            result_summary=result_summary,
            error_message=(
                result_summary
                if is_error
                else None
            ),
        )

        logger.info(
            "MCP 工具调用完成："
            "server=%s tool=%s "
            "success=%s duration_ms=%s",
            server_name,
            tool_name,
            not is_error,
            duration_ms,
        )

        return {
            "server_name": server_name,
            "tool_name": tool_name,
            "is_error": is_error,
            "content": content,
            "structured_content": (
                structured_content
            ),
        }


mcp_client_manager = MCPClientManager()

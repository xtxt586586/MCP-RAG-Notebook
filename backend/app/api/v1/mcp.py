import logging
from typing import Any
import json

from fastapi import APIRouter, HTTPException
from pydantic import (
    BaseModel,
    Field,
    field_validator,
)

from app.services.mcp.client_manager import (
    mcp_client_manager,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/mcp",
    tags=["MCP Client"],
)


class MCPToolCallRequest(BaseModel):
    tool_name: str = Field(
        min_length=1,
        max_length=200,
    )

    arguments: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(
        cls,
        value: str,
    ) -> str:
        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError(
                "tool_name 不能为空"
            )

        return normalized_value


@router.get("/servers")
async def list_mcp_servers() -> dict:
    try:
        servers = (
            mcp_client_manager.list_servers()
        )

        return {
            "count": len(servers),
            "servers": servers,
        }

    except FileNotFoundError as exc:
        logger.exception(
            "MCP Server 配置文件不存在"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    except (ValueError, json.JSONDecodeError) as exc:
        logger.exception(
            "MCP Server 配置无效"
        )

        raise HTTPException(
            status_code=500,
            detail="MCP Server 配置无效",
        ) from exc

    except Exception as exc:
        logger.exception(
            "读取 MCP Server 配置失败"
        )

        raise HTTPException(
            status_code=500,
            detail="读取 MCP Server 配置失败",
        ) from exc


@router.get(
    "/servers/{server_name}/tools"
)
async def list_mcp_tools(
    server_name: str,
) -> dict:
    try:
        tools = await (
            mcp_client_manager.list_tools(
                server_name
            )
        )

        return {
            "server_name": server_name,
            "count": len(tools),
            "tools": tools,
        }

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="连接 MCP Server 超时",
        ) from exc

    except Exception as exc:
        logger.exception(
            "获取 MCP 工具列表失败："
            "server=%s",
            server_name,
        )

        raise HTTPException(
            status_code=502,
            detail="无法连接 MCP Server",
        ) from exc


@router.post(
    "/servers/{server_name}/call"
)
async def call_mcp_tool(
    server_name: str,
    request: MCPToolCallRequest,
) -> dict:
    try:
        return await (
            mcp_client_manager.call_tool(
                server_name=server_name,
                tool_name=request.tool_name,
                arguments=request.arguments,
            )
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="MCP 工具调用超时",
        ) from exc

    except Exception as exc:
        logger.exception(
            "MCP 工具调用失败："
            "server=%s tool=%s",
            server_name,
            request.tool_name,
        )

        raise HTTPException(
            status_code=502,
            detail="MCP 工具调用失败",
        ) from exc
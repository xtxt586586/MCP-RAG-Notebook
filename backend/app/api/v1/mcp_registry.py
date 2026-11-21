from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.models import MCPServer
from app.services.mcp.tool_catalog import mcp_tool_catalog
from app.schemas.mcp_server import (
    MCPServerCreate,
    MCPServerResponse,
    MCPServerUpdate,
)


router = APIRouter(
    prefix="/mcp/registry",
    tags=["MCP Server Registry"],
)


def require_dynamic_registry() -> None:
    if not settings.mcp_dynamic_registry_enabled:
        raise HTTPException(status_code=403, detail="动态 MCP 配置已禁用，请使用受信任的静态配置")


@router.get('/mode')
async def registry_mode(current_user: CurrentUser) -> dict[str, bool]:
    return {'dynamic_enabled': settings.mcp_dynamic_registry_enabled}


def to_response(
    server: MCPServer,
) -> MCPServerResponse:
    return MCPServerResponse(
        id=server.id,
        name=server.name,
        transport=server.transport,
        command=server.command,
        args=list(server.arguments or []),
        url=server.url,
        enabled=server.enabled,
        allowed_tools=list(
            server.allowed_tools or []
        ),
        timeout_seconds=server.timeout_seconds,
        secret_reference=(
            server.secret_reference
        ),
    )


def validate_definition(
    *,
    transport: str,
    command: str | None,
    url: str | None,
) -> None:
    if transport == "stdio" and not command:
        raise HTTPException(
            status_code=422,
            detail="stdio Server 必须提供 command",
        )

    if (
        transport == "streamable_http"
        and not url
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "streamable_http Server "
                "必须提供 url"
            ),
        )


async def get_server_or_404(
    *,
    server_id: UUID,
    db: AsyncSession,
) -> MCPServer:
    result = await db.execute(
        select(MCPServer).where(
            MCPServer.id == server_id
        )
    )

    server = result.scalar_one_or_none()

    if server is None:
        raise HTTPException(
            status_code=404,
            detail="MCP Server 不存在",
        )

    return server


@router.get(
    "/servers",
    response_model=list[MCPServerResponse],
)
async def list_registry_servers(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[MCPServerResponse]:
    result = await db.execute(
        select(MCPServer).order_by(
            MCPServer.name.asc()
        )
    )

    servers = result.scalars().all()

    return [
        to_response(server)
        for server in servers
    ]


@router.post(
    "/servers",
    response_model=MCPServerResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_dynamic_registry)],
)
async def create_registry_server(
    request: MCPServerCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MCPServerResponse:
    validate_definition(
        transport=request.transport,
        command=request.command,
        url=request.url,
    )

    server = MCPServer(
        name=request.name,
        transport=request.transport,
        command=request.command,
        arguments=request.args,
        url=request.url,
        enabled=request.enabled,
        allowed_tools=request.allowed_tools,
        timeout_seconds=request.timeout_seconds,
        secret_reference=request.secret_reference,
    )

    db.add(server)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()

        raise HTTPException(
            status_code=409,
            detail=(
                "MCP Server 名称已经存在"
            ),
        ) from exc

    await db.refresh(server)
    await mcp_tool_catalog.clear_cache()

    return to_response(server)


@router.get(
    "/servers/{server_id}",
    response_model=MCPServerResponse,
)
async def get_registry_server(
    server_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MCPServerResponse:
    server = await get_server_or_404(
        server_id=server_id,
        db=db,
    )

    return to_response(server)


@router.patch(
    "/servers/{server_id}",
    response_model=MCPServerResponse,
    dependencies=[Depends(require_dynamic_registry)],
)
async def update_registry_server(
    server_id: UUID,
    request: MCPServerUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MCPServerResponse:
    server = await get_server_or_404(
        server_id=server_id,
        db=db,
    )

    update_data = request.model_dump(
        exclude_unset=True
    )

    transport = update_data.get(
        "transport",
        server.transport,
    )

    command = update_data.get(
        "command",
        server.command,
    )

    url = update_data.get(
        "url",
        server.url,
    )

    validate_definition(
        transport=transport,
        command=command,
        url=url,
    )

    if "name" in update_data:
        server.name = update_data["name"]

    if "transport" in update_data:
        server.transport = update_data[
            "transport"
        ]

    if "command" in update_data:
        server.command = update_data[
            "command"
        ]

    if "args" in update_data:
        server.arguments = update_data[
            "args"
        ]

    if "url" in update_data:
        server.url = update_data["url"]

    if "enabled" in update_data:
        server.enabled = update_data[
            "enabled"
        ]

    if "allowed_tools" in update_data:
        server.allowed_tools = update_data[
            "allowed_tools"
        ]

    if "timeout_seconds" in update_data:
        server.timeout_seconds = (
            update_data["timeout_seconds"]
        )

    if "secret_reference" in update_data:
        server.secret_reference = (
            update_data["secret_reference"]
        )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()

        raise HTTPException(
            status_code=409,
            detail=(
                "MCP Server 名称已经存在"
            ),
        ) from exc

    await db.refresh(server)
    await mcp_tool_catalog.clear_cache()

    return to_response(server)


@router.delete(
    "/servers/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_dynamic_registry)],
)
async def delete_registry_server(
    server_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    server = await get_server_or_404(
        server_id=server_id,
        db=db,
    )

    await db.delete(server)
    await db.commit()
    await mcp_tool_catalog.clear_cache()

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )

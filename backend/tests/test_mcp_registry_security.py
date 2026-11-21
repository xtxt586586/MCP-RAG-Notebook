from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.dependencies import get_current_user
from app.api.v1 import mcp, mcp_registry
from app.core.config import settings
from app.core.database import get_db
from app.services.mcp.client_manager import MCPClientManager


@pytest.mark.asyncio
async def test_dynamic_registry_rejects_mutations_by_default(monkeypatch):
    monkeypatch.setattr(settings, 'mcp_dynamic_registry_enabled', False)
    app = FastAPI()
    app.include_router(mcp_registry.router)
    app.dependency_overrides[get_current_user] = lambda: object()
    app.dependency_overrides[get_db] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        server_id = uuid4()
        for method, path, body in [
            ('POST', '/mcp/registry/servers', {'name': 'unsafe', 'command': 'sh'}),
            ('PATCH', f'/mcp/registry/servers/{server_id}', {'command': 'sh'}),
            ('DELETE', f'/mcp/registry/servers/{server_id}', None),
        ]:
            response = await client.request(method, path, json=body)
            assert response.status_code == 403


@pytest.mark.asyncio
async def test_disabled_registry_cannot_override_trusted_static_server(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'mcp_dynamic_registry_enabled', False)
    config = tmp_path / 'servers.json'
    config.write_text('{"servers":{"trusted":{"enabled":true,"command":"safe"}}}', encoding='utf-8')
    monkeypatch.setattr(settings, 'mcp_servers_config', str(config))

    def database_must_not_be_accessed():
        raise AssertionError('disabled registry must not query or launch database configuration')

    monkeypatch.setattr('app.services.mcp.client_manager.AsyncSessionLocal', database_must_not_be_accessed)
    manager = MCPClientManager()
    assert (await manager._get_server_config('trusted'))['command'] == 'safe'
    with pytest.raises(KeyError):
        await manager._get_server_config('database-only')


@pytest.mark.asyncio
async def test_tool_discovery_requires_login():
    app = FastAPI()
    app.include_router(mcp.router)
    app.dependency_overrides[get_db] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/mcp/servers/rag_notebook/tools')
    assert response.status_code == 401


def test_tool_call_requires_global_and_server_allowlists(monkeypatch):
    monkeypatch.setattr(settings, 'mcp_client_allowed_tools', 'trusted:read,trusted:write')
    manager = MCPClientManager()
    manager._ensure_tool_allowed(server_name='trusted', tool_name='read', server_config={'allowed_tools': ['read']})
    with pytest.raises(PermissionError):
        manager._ensure_tool_allowed(server_name='other', tool_name='read', server_config={})
    with pytest.raises(PermissionError):
        manager._ensure_tool_allowed(server_name='trusted', tool_name='write', server_config={'allowed_tools': ['read']})

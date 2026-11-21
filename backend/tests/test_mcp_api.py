import pytest

from app.api.v1 import mcp as mcp_api


@pytest.mark.asyncio
async def test_list_mcp_servers_returns_sync_manager_result(monkeypatch):
    servers = [
        {"name": "rag_notebook", "enabled": True, "transport": "stdio"},
    ]
    monkeypatch.setattr(
        mcp_api.mcp_client_manager,
        "list_servers",
        lambda: servers,
    )

    result = await mcp_api.list_mcp_servers()

    assert result == {"count": 1, "servers": servers}

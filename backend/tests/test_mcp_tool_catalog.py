from app.services.mcp.tool_catalog import MCPToolCatalog
import pytest
import asyncio


def test_catalog_does_not_expose_project_owned_search_tools(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.mcp.tool_catalog.settings.mcp_agent_allowed_tools",
        "rag_notebook:search_knowledge_base,"
        "rag_notebook:search_knowledge,"
        "rag_notebook:ask_knowledge_base,"
        "rag_notebook:create_note,fetch:fetch",
    )

    allowed_tools = MCPToolCatalog._allowed_tools()

    assert allowed_tools == {
        "rag_notebook:create_note",
        "fetch:fetch",
    }


@pytest.mark.asyncio
async def test_catalog_reuses_server_schema_cache(monkeypatch) -> None:
    calls = 0

    async def fake_list_tools(_server_name):
        nonlocal calls
        calls += 1
        return [{"name": "fetch", "description": "fetch", "inputSchema": {}}]

    monkeypatch.setattr(
        "app.services.mcp.tool_catalog.settings.mcp_agent_allowed_tools",
        "fetch:fetch",
    )
    monkeypatch.setattr(
        "app.services.mcp.tool_catalog.mcp_client_manager.list_tools",
        fake_list_tools,
    )

    catalog = MCPToolCatalog()
    await catalog.build_catalog()
    await catalog.build_catalog()

    assert calls == 1


@pytest.mark.asyncio
async def test_catalog_caches_failed_server_discovery(monkeypatch) -> None:
    calls = 0

    async def failed_list_tools(_server_name):
        nonlocal calls
        calls += 1
        raise TimeoutError("server unavailable")

    monkeypatch.setattr(
        "app.services.mcp.tool_catalog.settings.mcp_agent_allowed_tools",
        "optional:tool",
    )
    monkeypatch.setattr(
        "app.services.mcp.tool_catalog.mcp_client_manager.list_tools",
        failed_list_tools,
    )

    catalog = MCPToolCatalog()
    first = await catalog.build_catalog()
    second = await catalog.build_catalog()

    assert first == ([], {})
    assert second == ([], {})
    assert calls == 1


@pytest.mark.asyncio
async def test_catalog_increases_cooldown_after_repeated_failures(monkeypatch) -> None:
    now = 100.0
    calls = 0

    def fake_perf_counter():
        return now

    async def failed_list_tools(_server_name):
        nonlocal calls
        calls += 1
        raise TimeoutError("server unavailable")

    monkeypatch.setattr(
        "app.services.mcp.tool_catalog.settings.mcp_agent_allowed_tools",
        "optional:tool",
    )
    monkeypatch.setattr(
        "app.services.mcp.tool_catalog.perf_counter",
        fake_perf_counter,
    )
    monkeypatch.setattr(
        "app.services.mcp.tool_catalog.mcp_client_manager.list_tools",
        failed_list_tools,
    )

    catalog = MCPToolCatalog()
    await catalog.build_catalog()
    assert catalog._cache["optional"][0] == 160.0

    now = 161.0
    await catalog.build_catalog()
    assert catalog._cache["optional"][0] == 281.0

    now = 200.0
    await catalog.build_catalog()
    assert calls == 2


@pytest.mark.asyncio
async def test_catalog_deduplicates_concurrent_discovery(monkeypatch) -> None:
    calls = 0

    async def fake_list_tools(_server_name):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return [{"name": "tool", "description": "tool", "inputSchema": {}}]

    monkeypatch.setattr(
        "app.services.mcp.tool_catalog.settings.mcp_agent_allowed_tools",
        "server:tool",
    )
    monkeypatch.setattr(
        "app.services.mcp.tool_catalog.mcp_client_manager.list_tools",
        fake_list_tools,
    )

    catalog = MCPToolCatalog()
    results = await asyncio.gather(
        catalog.build_catalog(),
        catalog.build_catalog(),
    )

    assert results[0] == results[1]
    assert calls == 1


@pytest.mark.asyncio
async def test_list_tools_rejects_missing_stdio_script_before_spawn(
    monkeypatch,
    tmp_path,
) -> None:
    from app.services.mcp.client_manager import MCPClientManager

    manager = MCPClientManager()

    async def fake_server_config(_server_name):
        return {
            "transport": "stdio",
            "args": [str(tmp_path / "missing_server.py")],
            "timeout_seconds": 30,
        }

    monkeypatch.setattr(manager, "_get_server_config", fake_server_config)

    with pytest.raises(FileNotFoundError, match="脚本不存在"):
        await manager.list_tools("missing")

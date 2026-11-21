import json

import pytest

from app.services.agent import langchain_tools


@pytest.mark.asyncio
async def test_build_mcp_tools_uses_langchain_tool_name_and_invokes(monkeypatch) -> None:
    async def fake_build_catalog():
        return (
            [
                {
                    "function": {
                        "name": "github__search_repositories",
                        "description": "Search GitHub repositories.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query",
                                },
                                "limit": {
                                    "type": "integer",
                                },
                            },
                            "required": ["query"],
                        },
                    }
                }
            ],
            {
                "github__search_repositories": (
                    "github",
                    "search_repositories",
                )
            },
        )

    calls = []

    async def fake_call_tool(**kwargs):
        calls.append(kwargs)
        return {"repositories": ["example/project"]}

    monkeypatch.setattr(
        langchain_tools.mcp_tool_catalog,
        "build_catalog",
        fake_build_catalog,
    )
    monkeypatch.setattr(
        langchain_tools.mcp_client_manager,
        "call_tool",
        fake_call_tool,
    )

    tools = await langchain_tools.build_mcp_tools(
        user_id="user-123",
        knowledge_base_id="kb-456",
        access_token="request-token",
    )

    assert len(tools) == 1
    assert tools[0].name == "mcp__github__search_repositories"

    result = await tools[0].ainvoke({"query": "modelcontextprotocol"})

    assert json.loads(result) == {"repositories": ["example/project"]}
    assert calls == [
        {
            "server_name": "github",
            "tool_name": "search_repositories",
            "arguments": {"query": "modelcontextprotocol"},
            "user_id": "user-123",
            "access_token": "request-token",
        }
    ]

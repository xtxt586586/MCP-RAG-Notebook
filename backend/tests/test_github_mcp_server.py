import base64

import pytest

from mcp_servers.github.server import (
    _decode_file_content,
    _page_size,
    _repo_path,
)


def test_github_repo_path_encodes_names() -> None:
    assert _repo_path("modelcontextprotocol", "servers", "issues") == (
        "/repos/modelcontextprotocol/servers/issues"
    )


def test_github_repo_path_rejects_malformed_names() -> None:
    with pytest.raises(ValueError):
        _repo_path("owner/name", "repo")


def test_github_page_size_is_bounded() -> None:
    assert _page_size(-1) == 1
    assert _page_size(1000) == 20


def test_github_file_content_is_decoded_and_truncated() -> None:
    content = "hello MCP"
    item = {
        "type": "file",
        "name": "README.md",
        "path": "README.md",
        "size": len(content),
        "content": base64.b64encode(content.encode()).decode(),
    }

    result = _decode_file_content(item)

    assert result["content"] == content
    assert result["truncated"] is False

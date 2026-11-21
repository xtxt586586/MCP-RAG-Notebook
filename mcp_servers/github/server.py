import base64
import os
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP


API_BASE_URL = "https://api.github.com"
MAX_PER_PAGE = 20
MAX_FILE_CHARS = 30000

mcp = FastMCP("MCP-RAG-Notebook GitHub")


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MCP-RAG-Notebook",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _page_size(per_page: int) -> int:
    return max(1, min(per_page, MAX_PER_PAGE))


def _repo_path(owner: str, repo: str, suffix: str = "") -> str:
    owner = owner.strip()
    repo = repo.strip()
    if not owner or not repo or "/" in owner or "/" in repo:
        raise ValueError("owner 和 repo 必须分别是有效的 GitHub 名称")
    base = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
    return f"{base}/{suffix.lstrip('/')}" if suffix else base


async def _get_json(path: str, params: dict[str, Any] | None = None) -> Any:
    try:
        async with httpx.AsyncClient(
            base_url=API_BASE_URL,
            headers=_headers(),
            timeout=httpx.Timeout(20.0, connect=8.0),
        ) as client:
            response = await client.get(path, params=params)
    except httpx.TimeoutException as exc:
        raise RuntimeError("连接 GitHub API 超时，请检查网络和代理") from exc
    except httpx.RequestError as exc:
        raise RuntimeError("无法连接 GitHub API，请检查 Docker 容器的网络和代理") from exc

    if response.is_error:
        try:
            message = response.json().get("message", response.reason_phrase)
        except (ValueError, AttributeError):
            message = response.reason_phrase
        if response.status_code in {401, 403}:
            raise RuntimeError(
                f"GitHub API 拒绝请求（HTTP {response.status_code}）：{message}。"
                "代码搜索通常需要配置 GITHUB_PERSONAL_ACCESS_TOKEN。"
            )
        if response.status_code == 404:
            raise RuntimeError("GitHub 仓库、文件或议题不存在，或当前令牌无权访问")
        raise RuntimeError(f"GitHub API 请求失败（HTTP {response.status_code}）：{message}")
    return response.json()


def _decode_file_content(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("type") != "file":
        return {
            "type": item.get("type"),
            "name": item.get("name"),
            "path": item.get("path"),
            "html_url": item.get("html_url"),
        }

    encoded = item.get("content", "")
    try:
        content = base64.b64decode(encoded).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        content = ""
    truncated = len(content) > MAX_FILE_CHARS
    return {
        "type": "file",
        "name": item.get("name"),
        "path": item.get("path"),
        "size": item.get("size"),
        "html_url": item.get("html_url"),
        "content": content[:MAX_FILE_CHARS],
        "truncated": truncated,
    }


@mcp.tool()
async def search_repositories(query: str, per_page: int = 5) -> dict[str, Any]:
    """Search public GitHub repositories by keywords, language, or owner."""
    query = query.strip()
    if not query:
        raise ValueError("query 不能为空")
    result = await _get_json(
        "/search/repositories",
        {"q": query, "per_page": _page_size(per_page), "sort": "stars", "order": "desc"},
    )
    return {
        "total_count": result.get("total_count", 0),
        "items": [
            {
                "full_name": item.get("full_name"),
                "description": item.get("description"),
                "html_url": item.get("html_url"),
                "stars": item.get("stargazers_count"),
                "language": item.get("language"),
                "updated_at": item.get("updated_at"),
            }
            for item in result.get("items", [])
        ],
    }


@mcp.tool()
async def get_file_contents(
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Read a file or list a directory in a GitHub repository."""
    path = path.strip().strip("/")
    if not path:
        raise ValueError("path 不能为空")
    params = {"ref": ref.strip()} if ref and ref.strip() else None
    item = await _get_json(
        _repo_path(owner, repo, f"contents/{quote(path, safe='/')}"),
        params,
    )
    if isinstance(item, list):
        return [
            {
                "type": child.get("type"),
                "name": child.get("name"),
                "path": child.get("path"),
                "html_url": child.get("html_url"),
            }
            for child in item[:100]
        ]
    if not isinstance(item, dict):
        raise RuntimeError("GitHub 返回了无法识别的文件内容")
    return _decode_file_content(item)


@mcp.tool()
async def search_code(query: str, per_page: int = 5) -> dict[str, Any]:
    """Search source code on GitHub; a personal access token is recommended."""
    query = query.strip()
    if not query:
        raise ValueError("query 不能为空")
    result = await _get_json(
        "/search/code",
        {"q": query, "per_page": _page_size(per_page)},
    )
    return {
        "total_count": result.get("total_count", 0),
        "items": [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "repository": (item.get("repository") or {}).get("full_name"),
                "html_url": item.get("html_url"),
            }
            for item in result.get("items", [])
        ],
    }


@mcp.tool()
async def list_issues(
    owner: str,
    repo: str,
    state: str = "open",
    per_page: int = 10,
) -> dict[str, Any]:
    """List repository issues, excluding pull requests."""
    if state not in {"open", "closed", "all"}:
        raise ValueError("state 必须是 open、closed 或 all")
    result = await _get_json(
        _repo_path(owner, repo, "issues"),
        {"state": state, "per_page": _page_size(per_page)},
    )
    issues = result if isinstance(result, list) else []
    return {
        "items": [
            {
                "number": item.get("number"),
                "title": item.get("title"),
                "state": item.get("state"),
                "html_url": item.get("html_url"),
                "created_at": item.get("created_at"),
                "body": (item.get("body") or "")[:4000],
            }
            for item in issues
            if "pull_request" not in item
        ]
    }


@mcp.tool()
async def get_issue(owner: str, repo: str, issue_number: int) -> dict[str, Any]:
    """Get a GitHub issue by repository and issue number."""
    if issue_number < 1:
        raise ValueError("issue_number 必须大于 0")
    item = await _get_json(_repo_path(owner, repo, f"issues/{issue_number}"))
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "html_url": item.get("html_url"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "body": (item.get("body") or "")[:8000],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")

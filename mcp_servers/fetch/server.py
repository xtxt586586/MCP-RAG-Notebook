from __future__ import annotations

import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP


DEFAULT_MAX_LENGTH = 5_000
MAX_MAX_LENGTH = 50_000
REQUEST_TIMEOUT = 30.0

mcp = FastMCP("Local Fetch")


class _TextExtractor(HTMLParser):
    """Extract readable text while ignoring page chrome and scripts."""

    _ignored_tags = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._ignored_tags:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag.lower() in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._ignored_tags and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and tag.lower() in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self._parts))
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r"\n[ ]+", "\n", value)
        return re.sub(r"\n{3,}", "\n\n", value).strip()


def _validate_url(url: str) -> str:
    normalized = url.strip()
    parsed = urlparse(normalized)

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url 必须是 http 或 https 地址")

    hostname = parsed.hostname
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as exc:
        raise ValueError(f"无法解析主机：{hostname}") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast:
            raise ValueError("不允许访问本机或内网地址")

    return normalized


@mcp.tool()
async def fetch(
    url: str,
    max_length: int = DEFAULT_MAX_LENGTH,
    start_index: int = 0,
) -> str:
    """Fetch a public web page and return readable text."""
    normalized_url = _validate_url(url)

    if not 1 <= max_length <= MAX_MAX_LENGTH:
        raise ValueError(f"max_length 必须在 1 到 {MAX_MAX_LENGTH} 之间")
    if start_index < 0:
        raise ValueError("start_index 不能小于 0")

    headers = {
        "User-Agent": "MCP-RAG-Notebook/1.0 (local fetch)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    }

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        # A validated public URL may redirect to an internal address. Reject
        # redirects rather than following an unvalidated second destination.
        follow_redirects=False,
        # Fetch is intended for directly reachable public/domestic sites;
        # it must not depend on the global proxy used by other MCP servers.
        trust_env=False,
    ) as client:
        response = await client.get(normalized_url, headers=headers)
        response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type:
        parser = _TextExtractor()
        parser.feed(response.text)
        content = parser.text()
    else:
        content = response.text.strip()

    return content[start_index : start_index + max_length]


if __name__ == "__main__":
    mcp.run(transport="stdio")

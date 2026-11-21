import socket

import httpx
import pytest

from mcp_servers.fetch import server


def test_fetch_url_rejects_loopback(monkeypatch):
    monkeypatch.setattr(server.socket, "getaddrinfo", lambda *args: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
    ])
    with pytest.raises(ValueError, match="不允许访问"):
        server._validate_url("http://example.org/")


@pytest.mark.asyncio
async def test_fetch_does_not_follow_redirect_to_internal_host(monkeypatch):
    monkeypatch.setattr(server.socket, "getaddrinfo", lambda *args: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
    ])
    requests = []

    def handle(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda **kwargs: client_class(
        transport=httpx.MockTransport(handle), **kwargs
    ))
    with pytest.raises(httpx.HTTPStatusError):
        await server.fetch("https://example.org/")
    assert requests == ["https://example.org/"]

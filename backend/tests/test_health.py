import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_health_check() -> None:
    transport = httpx.ASGITransport(
        app=app,
    )

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/health"
        )

    assert response.status_code == 200
    assert response.headers["X-Process-Time-ms"]

    assert response.json() == {
        "status": "ok",
        "service": (
            "MCP-RAG-Notebook backend"
        ),
    }


@pytest.mark.asyncio
async def test_request_metrics_endpoint() -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        await client.get("/health")
        response = await client.get("/health/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert any(
        item["route"] == "/health"
        for item in payload["metrics"]
    )

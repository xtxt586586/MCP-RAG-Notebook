import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_cookie_authenticated_write_requires_csrf_token() -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        client.cookies.set("rag_access_token", "cookie-session")

        missing_token = await client.post("/api/v1/auth/logout")
        assert missing_token.status_code == 403

        client.cookies.set("rag_csrf_token", "csrf-value")
        valid_token = await client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": "csrf-value"},
        )
        assert valid_token.status_code == 204

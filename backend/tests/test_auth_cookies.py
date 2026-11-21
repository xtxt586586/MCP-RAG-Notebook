from uuid import uuid4

from starlette.responses import Response

from app.api.v1 import auth as auth_api
from app.core.config import settings
from app.schemas.auth import TokenResponse, UserResponse


def test_set_auth_cookies_writes_access_refresh_and_csrf_tokens(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_cookie_secure", True)
    response = Response()
    token_response = TokenResponse(
        access_token="access-token",
        refresh_token="refresh-token",
        expires_in=1800,
        user=UserResponse(
            id=uuid4(),
            email="cookie-test@example.com",
            is_active=True,
        ),
    )

    auth_api.set_auth_cookies(response, token_response)

    set_cookie_headers = response.headers.getlist("set-cookie")
    assert len(set_cookie_headers) == 3

    access_cookie = next(
        value for value in set_cookie_headers
        if value.startswith("rag_access_token=")
    )
    refresh_cookie = next(
        value for value in set_cookie_headers
        if value.startswith("rag_refresh_token=")
    )
    csrf_cookie = next(
        value for value in set_cookie_headers
        if value.startswith("rag_csrf_token=")
    )

    for cookie in (access_cookie, refresh_cookie):
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie
        assert "Max-Age=1800" in cookie or "Max-Age=604800" in cookie

    assert "HttpOnly" not in csrf_cookie
    assert "Secure" in csrf_cookie
    assert "SameSite=lax" in csrf_cookie

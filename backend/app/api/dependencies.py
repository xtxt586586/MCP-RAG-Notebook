from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models import User


bearer_scheme = HTTPBearer(
    auto_error=False,
)

ACCESS_TOKEN_COOKIE = "rag_access_token"
CSRF_TOKEN_COOKIE = "rag_csrf_token"
CSRF_TOKEN_HEADER = "X-CSRF-Token"


def get_request_access_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    if credentials is not None and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    return request.cookies.get(ACCESS_TOKEN_COOKIE)


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Annotated[
        AsyncSession,
        Depends(get_db),
    ],
) -> User:
    authentication_error = HTTPException(
        status_code=401,
        detail="认证凭证无效或已经过期",
        headers={
            "WWW-Authenticate": "Bearer",
        },
    )

    token = get_request_access_token(request, credentials)
    if not token:
        raise authentication_error

    try:
        user_id = decode_token(
            token,
            expected_type="access",
        )
    except ValueError as exc:
        raise authentication_error from exc

    result = await db.execute(
        select(User).where(
            User.id == user_id,
        )
    )

    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise authentication_error

    return user


CurrentUser = Annotated[
    User,
    Depends(get_current_user),
]

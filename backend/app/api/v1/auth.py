import logging
import secrets

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    CSRF_TOKEN_COOKIE,
    CurrentUser,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import KnowledgeBase, User
from app.schemas import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)


router = APIRouter(
    prefix="/auth",
    tags=["用户认证"],
)

logger = logging.getLogger(__name__)

ACCESS_TOKEN_COOKIE = "rag_access_token"
REFRESH_TOKEN_COOKIE = "rag_refresh_token"


def build_token_response(
    user: User,
) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=(
            settings.jwt_access_token_expire_minutes
            * 60
        ),
        user=UserResponse.model_validate(user),
    )


def set_auth_cookies(response: Response, token_response: TokenResponse) -> None:
    csrf_token = secrets.token_urlsafe(32)
    cookie_options = {
        "httponly": True,
        "secure": settings.auth_cookie_secure,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        token_response.access_token,
        max_age=token_response.expires_in,
        **cookie_options,
    )
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        token_response.refresh_token,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        **cookie_options,
    )
    response.set_cookie(
        CSRF_TOKEN_COOKIE,
        csrf_token,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    request: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    existing_result = await db.execute(
        select(User.id).where(
            User.email == request.email,
        )
    )

    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="该邮箱已经注册",
        )

    user = User(
        email=request.email,
        password_hash=hash_password(
            request.password
        ),
    )

    try:
        db.add(user)
        # Generate the Python-side UUID before using it as the foreign key of
        # the account's initial personal knowledge base.
        await db.flush()

        # Every account starts with one personal knowledge base. The row is
        # kept as an internal partition key, while the UI does not expose
        # switching.
        db.add(
            KnowledgeBase(
                user_id=user.id,
                name="我的知识库",
                description="当前账户的个人知识库",
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()

        # Only a unique-email violation means the account already exists.
        # Other integrity errors must not be reported as a misleading 409.
        error_text = str(getattr(exc, "orig", exc)).lower()
        if "email" in error_text and (
            "unique" in error_text or "duplicate" in error_text
        ):
            raise HTTPException(
                status_code=409,
                detail="该邮箱已经注册",
            ) from exc

        logger.exception("注册事务失败")
        raise HTTPException(
            status_code=500,
            detail="注册失败，请稍后重试",
        ) from exc

    await db.refresh(user)

    token_response = build_token_response(user)
    set_auth_cookies(response, token_response)
    return token_response


@router.post(
    "/login",
    response_model=TokenResponse,
)
async def login(
    request: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    result = await db.execute(
        select(User).where(
            User.email == request.email,
        )
    )

    user = result.scalar_one_or_none()

    if (
        user is None
        or not verify_password(
            request.password,
            user.password_hash,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="邮箱或密码错误",
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="用户已经被禁用",
        )

    token_response = build_token_response(user)
    set_auth_cookies(response, token_response)
    return token_response


@router.post(
    "/refresh",
    response_model=TokenResponse,
)
async def refresh_access_token(
    request: RefreshTokenRequest,
    response: Response,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    refresh_token = request.refresh_token or http_request.cookies.get(REFRESH_TOKEN_COOKIE)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh Token 缺失")

    try:
        user_id = decode_token(
            refresh_token,
            expected_type="refresh",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail="Refresh Token 无效或已经过期",
        ) from exc

    result = await db.execute(
        select(User).where(
            User.id == user_id,
        )
    )

    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Refresh Token 对应的用户无效",
        )

    token_response = build_token_response(user)
    set_auth_cookies(response, token_response)
    return token_response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(ACCESS_TOKEN_COOKIE, path="/")
    response.delete_cookie(REFRESH_TOKEN_COOKIE, path="/")
    response.delete_cookie(CSRF_TOKEN_COOKIE, path="/")


@router.get(
    "/me",
    response_model=UserResponse,
)
async def get_me(
    current_user: CurrentUser,
) -> UserResponse:
    return UserResponse.model_validate(
        current_user
    )

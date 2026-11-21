from datetime import datetime, timedelta, timezone
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


password_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(
    plain_password: str,
    password_hash: str,
) -> bool:
    return password_context.verify(
        plain_password,
        password_hash,
    )


def _create_token(
    *,
    subject: UUID | str,#令牌主题
    token_type: str,#令牌类型
    expires_delta: timedelta,#有效期时长
) -> str:
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(
    subject: UUID | str,
) -> str:
    return _create_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(
            minutes=(
                settings
                .jwt_access_token_expire_minutes
            )
        ),
    )


def create_refresh_token(
    subject: UUID | str,
) -> str:
    return _create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(
            days=(
                settings
                .jwt_refresh_token_expire_days
            )
        ),
    )


def decode_token(
    token: str,
    *,
    expected_type: str,
) -> UUID:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        if payload.get("type") != expected_type:
            raise JWTError("Token 类型错误")

        subject = payload.get("sub")

        if not isinstance(subject, str):
            raise JWTError("Token 缺少用户标识")

        return UUID(subject)

    except (JWTError, ValueError) as exc:
        raise ValueError(
            "Token 无效或已经过期"
        ) from exc
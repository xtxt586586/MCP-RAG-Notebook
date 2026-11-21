from uuid import uuid4

import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_and_verify() -> None:
    password = "TestPassword123!"

    password_hash = hash_password(password)

    assert password_hash != password

    assert verify_password(
        password,
        password_hash,
    )

    assert not verify_password(
        "WrongPassword123!",
        password_hash,
    )


def test_access_token() -> None:
    user_id = uuid4()

    token = create_access_token(user_id)

    decoded_user_id = decode_token(
        token,
        expected_type="access",
    )

    assert decoded_user_id == user_id


def test_refresh_token() -> None:
    user_id = uuid4()

    token = create_refresh_token(user_id)

    decoded_user_id = decode_token(
        token,
        expected_type="refresh",
    )

    assert decoded_user_id == user_id


def test_token_type_isolation() -> None:
    user_id = uuid4()

    refresh_token = create_refresh_token(
        user_id
    )

    with pytest.raises(
        ValueError,
        match="Token 无效或已经过期",
    ):
        decode_token(
            refresh_token,
            expected_type="access",
        )
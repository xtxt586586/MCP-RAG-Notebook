from uuid import uuid4

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def main() -> None:
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

    user_id = uuid4()

    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id)

    assert access_token != refresh_token

    assert decode_token(
        access_token,
        expected_type="access",
    ) == user_id

    assert decode_token(
        refresh_token,
        expected_type="refresh",
    ) == user_id

    try:
        decode_token(
            refresh_token,
            expected_type="access",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Refresh Token 被错误识别为 Access Token"
        )

    print("密码哈希测试：通过")
    print("Access Token 测试：通过")
    print("Refresh Token 测试：通过")
    print("Token 类型隔离测试：通过")
    print("认证安全工具测试全部通过")


if __name__ == "__main__":
    main()
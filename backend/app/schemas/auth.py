from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def normalize_email(
        cls,
        value: EmailStr,
    ) -> str:
        return str(value).strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password(
        cls,
        value: str,
    ) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError(
                "密码的 UTF-8 长度不能超过 72 字节"
            )

        if not any(char.isalpha() for char in value):
            raise ValueError("密码必须包含字母")

        if not any(char.isdigit() for char in value):
            raise ValueError("密码必须包含数字")

        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(
        cls,
        value: EmailStr,
    ) -> str:
        return str(value).strip().lower()


class RefreshTokenRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=1)


class UserResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    email: EmailStr
    is_active: bool
    display_name: str | None = None
    phone: str | None = None
    gender: str | None = None
    bio: str | None = None
    avatar_url: str | None = None


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    gender: str | None = Field(default=None, max_length=20)
    bio: str | None = Field(default=None, max_length=1000)
    avatar_url: str | None = Field(default=None, max_length=500)


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)
    confirm_password: str = Field(min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码的 UTF-8 长度不能超过 72 字节")
        if not any(char.isalpha() for char in value):
            raise ValueError("密码必须包含字母")
        if not any(char.isdigit() for char in value):
            raise ValueError("密码必须包含数字")
        return value

    @field_validator("confirm_password")
    @classmethod
    def validate_confirm_password(cls, value: str, info) -> str:
        if info.data.get("new_password") and value != info.data["new_password"]:
            raise ValueError("两次输入的新密码不一致")
        return value


class AgentMemorySettingsResponse(BaseModel):
    max_turns: int
    default_max_turns: int


class AgentMemorySettingsRequest(BaseModel):
    max_turns: int = Field(ge=0, le=20)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse

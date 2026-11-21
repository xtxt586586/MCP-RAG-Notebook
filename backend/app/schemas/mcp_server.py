from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


MCPTransport = Literal[
    "stdio",
    "streamable_http",
]


class MCPServerCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
    )

    transport: MCPTransport = "stdio"

    command: str | None = Field(
        default=None,
        max_length=500,
    )

    args: list[str] = Field(
        default_factory=list,
    )

    url: str | None = Field(
        default=None,
        max_length=1000,
    )

    enabled: bool = True

    allowed_tools: list[str] = Field(
        default_factory=list,
    )

    timeout_seconds: float = Field(
        default=180.0,
        ge=1.0,
        le=600.0,
    )

    secret_reference: str | None = Field(
        default=None,
        max_length=500,
    )

    @field_validator("name")
    @classmethod
    def normalize_name(
        cls,
        value: str,
    ) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "Server 名称不能为空"
            )

        return value

    @field_validator("command", "url", "secret_reference")
    @classmethod
    def normalize_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()

        return value or None

    @field_validator("allowed_tools")
    @classmethod
    def normalize_allowed_tools(
        cls,
        value: list[str],
    ) -> list[str]:
        normalized: list[str] = []

        for item in value:
            item = item.strip()

            if item and item not in normalized:
                normalized.append(item)

        return normalized

    @model_validator(mode="after")
    def validate_transport_config(self):
        if self.transport == "stdio":
            if not self.command:
                raise ValueError(
                    "stdio Server 必须提供 command"
                )

        if self.transport == "streamable_http":
            if not self.url:
                raise ValueError(
                    "streamable_http Server 必须提供 url"
                )

        return self


class MCPServerUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    transport: MCPTransport | None = None

    command: str | None = Field(
        default=None,
        max_length=500,
    )

    args: list[str] | None = None

    url: str | None = Field(
        default=None,
        max_length=1000,
    )

    enabled: bool | None = None

    allowed_tools: list[str] | None = None

    timeout_seconds: float | None = Field(
        default=None,
        ge=1.0,
        le=600.0,
    )

    secret_reference: str | None = Field(
        default=None,
        max_length=500,
    )

    @field_validator("name")
    @classmethod
    def normalize_name(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError(
                "Server 名称不能为空"
            )

        return value

    @field_validator("command", "url", "secret_reference")
    @classmethod
    def normalize_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()

        return value or None

    @field_validator("allowed_tools")
    @classmethod
    def normalize_allowed_tools(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        if value is None:
            return None

        normalized: list[str] = []

        for item in value:
            item = item.strip()

            if item and item not in normalized:
                normalized.append(item)

        return normalized


class MCPServerResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    name: str
    transport: str
    command: str | None
    args: list[str]
    url: str | None
    enabled: bool
    allowed_tools: list[str]
    timeout_seconds: float
    secret_reference: str | None
import httpx

import json
from collections.abc import AsyncIterator
from app.core.config import settings
from typing import Any

class DeepSeekService:
    async def generate(
            self,
            *,
            messages: list[dict[str, str]],
            temperature: float = 0.2,
    ) -> str:
        url = (
            f"{settings.deepseek_base_url.rstrip(('/'))}"
            "/chat/completions"
        )

        headers = {
            "Authorization": (
                f"Bearer {settings.deepseek_api_key}"
            ),
            "Content-Type": "application/json",
        }

        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }

        async with httpx.AsyncClient(
            timeout=settings.deepseek_timeout_seconds,
        ) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                error_message = response.text[:1000]

                raise RuntimeError(
                    "DeepSeek API 请求失败："
                    f"HTTP {response.status_code},"
                    f"{error_message}"
                ) from exc

        response_data = response.json()

        choices = response_data.get("choices")

        if not choices:
            raise RuntimeError(
                "DeepSeek API 没有返回有效的 choices"
            )

        message = choices[0].get("message") or  {}
        content = message.get("content")

        if not content:
            raise RuntimeError(
                "DeepSeek API 返回的答案为空"
            )

        return  content



    async def stream_generate(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        url = (
            f"{settings.deepseek_base_url.rstrip('/')}"
            "/chat/completions"
        )

        headers = {
            "Authorization": (
                f"Bearer {settings.deepseek_api_key}"
            ),
            "Content-Type": "application/json",
        }

        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        async with httpx.AsyncClient(
            timeout=settings.deepseek_timeout_seconds,
        ) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=payload,
            ) as response:
                if response.is_error:
                    await response.aread()

                    raise RuntimeError(
                        "DeepSeek 流式请求失败："
                        f"HTTP {response.status_code}，"
                        f"{response.text[:1000]}"
                    )

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    if not line.startswith("data:"):
                        continue

                    data_text = line[5:].strip()

                    if data_text == "[DONE]":
                        break

                    try:
                        data = json.loads(data_text)
                    except json.JSONDecodeError:
                        continue

                    choices = data.get("choices") or []

                    if not choices:
                        continue

                    delta = (
                        choices[0].get("delta")
                        or {}
                    )

                    content = delta.get("content")

                    if content:
                        yield content

    async def complete_with_tools(
            self,
            *,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        url = (
            f"{settings.deepseek_base_url.rstrip('/')}"
            "/chat/completions"
        )

        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.1,
            "stream": False,
        }

        async with httpx.AsyncClient(
                timeout=settings.deepseek_timeout_seconds,
        ) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": (
                        f"Bearer "
                        f"{settings.deepseek_api_key}"
                    ),
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.is_error:
                raise RuntimeError(
                    "DeepSeek 工具选择请求失败："
                    f"HTTP {response.status_code}，"
                    f"{response.text[:1000]}"
                )

        response_data = response.json()
        choices = response_data.get("choices") or []

        if not choices:
            raise RuntimeError(
                "DeepSeek 没有返回 choices"
            )

        message = choices[0].get("message")

        if not message:
            raise RuntimeError(
                "DeepSeek 没有返回 message"
            )

        return message


deepseek_service = DeepSeekService()

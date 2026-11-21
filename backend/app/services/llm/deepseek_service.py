import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)

class DeepSeekService:
    @staticmethod
    def _timeout() -> httpx.Timeout:
        return httpx.Timeout(
            settings.deepseek_timeout_seconds,
            connect=settings.deepseek_connect_timeout_seconds,
        )

    @staticmethod
    def _attempts() -> int:
        return max(1, settings.deepseek_max_retries)

    @staticmethod
    def _retryable_status(status_code: int) -> bool:
        return status_code == 408 or status_code == 429 or status_code >= 500

    @staticmethod
    async def _backoff(attempt: int) -> None:
        if attempt < DeepSeekService._attempts():
            await asyncio.sleep(
                settings.deepseek_retry_backoff_seconds * attempt
            )

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

        response: httpx.Response | None = None
        for attempt in range(1, self._attempts() + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout(),
                    trust_env=settings.deepseek_trust_env,
                ) as client:
                    response = await client.post(
                        url,
                        headers=headers,
                        json=payload,
                    )
                if not self._retryable_status(response.status_code):
                    response.raise_for_status()
                    break
                if attempt == self._attempts():
                    response.raise_for_status()
                await self._backoff(attempt)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == self._attempts():
                    raise RuntimeError("DeepSeek API 网络请求失败，请检查网络或代理配置") from exc
                logger.warning("DeepSeek 请求失败，将进行第 %s 次重试", attempt + 1)
                await self._backoff(attempt)

        if response is None:
            raise RuntimeError("DeepSeek API 没有返回响应")

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

        for attempt in range(1, self._attempts() + 1):
            yielded_content = False
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout(),
                    trust_env=settings.deepseek_trust_env,
                ) as client:
                    async with client.stream(
                        "POST", url, headers=headers, json=payload
                    ) as response:
                        if response.is_error:
                            body = (await response.aread()).decode(errors="replace")[:1000]
                            if self._retryable_status(response.status_code) and attempt < self._attempts():
                                await self._backoff(attempt)
                                continue
                            raise RuntimeError(
                                "DeepSeek 流式请求失败："
                                f"HTTP {response.status_code}，{body}"
                            )

                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data:"):
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
                            content = (choices[0].get("delta") or {}).get("content")
                            if content:
                                yielded_content = True
                                yield content
                return
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if yielded_content or attempt == self._attempts():
                    raise RuntimeError("DeepSeek 流式请求网络失败，请检查网络或代理配置") from exc
                logger.warning("DeepSeek 流式请求失败，将进行第 %s 次重试", attempt + 1)
                await self._backoff(attempt)

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

        response: httpx.Response | None = None
        for attempt in range(1, self._attempts() + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout(),
                    trust_env=settings.deepseek_trust_env,
                ) as client:
                    response = await client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {settings.deepseek_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                if not self._retryable_status(response.status_code):
                    break
                if attempt < self._attempts():
                    await self._backoff(attempt)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == self._attempts():
                    raise RuntimeError("DeepSeek 工具选择网络请求失败") from exc
                await self._backoff(attempt)

        if response is None:
            raise RuntimeError("DeepSeek 工具选择没有返回响应")
        if response.is_error:
            raise RuntimeError(
                "DeepSeek 工具选择请求失败："
                f"HTTP {response.status_code}，{response.text[:1000]}"
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

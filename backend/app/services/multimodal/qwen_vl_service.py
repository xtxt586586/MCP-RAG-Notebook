from __future__ import annotations

import base64
import logging

import httpx

from app.core.config import settings
from app.services.multimodal.text_normalizer import (
    normalize_multimodal_text,
)


logger = logging.getLogger(__name__)


class QwenVLService:
    def _extract_content(self, payload: dict) -> str:
        choices = payload.get("choices") or []

        if not choices:
            return ""

        message = choices[0].get("message") or {}
        content = message.get("content", "")

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            texts: list[str] = []

            for item in content:
                if isinstance(item, dict):
                    text = item.get("text", "")

                    if text:
                        texts.append(str(text))

            return "\n".join(texts).strip()

        return str(content).strip()

    def describe_image_bytes(
        self,
        image_bytes: bytes,
        *,
        mime_type: str = "image/jpeg",
        prompt: str = (
            "请用简洁准确的中文描述这张图片。"
            "如果图片中有文字，请同时提取主要文字。"
            "不要猜测图片中不存在的信息。"
        ),
    ) -> str:
        if not settings.qwen_vl_enabled:
            return ""

        api_key = settings.qwen_vl_api_key.strip()

        if not api_key:
            logger.warning(
                "Qwen-VL 已启用，但没有配置 API Key"
            )
            return ""

        encoded_image = base64.b64encode(
            image_bytes
        ).decode("ascii")

        data_url = (
            f"data:{mime_type};base64,"
            f"{encoded_image}"
        )

        payload = {
            "model": settings.qwen_vl_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url,
                            },
                        },
                    ],
                }
            ],
            "temperature": 0.1,
        }

        url = (
            settings.qwen_vl_base_url.rstrip("/")
            + "/chat/completions"
        )

        try:
            with httpx.Client(
                timeout=settings.qwen_vl_timeout_seconds
            ) as client:
                response = client.post(
                    url,
                    headers={
                        "Authorization": (
                            f"Bearer {api_key}"
                        ),
                        "Content-Type": (
                            "application/json"
                        ),
                    },
                    json=payload,
                )

                response.raise_for_status()

            content = self._extract_content(
                response.json()
            )

            return normalize_multimodal_text(
                content
            )

        except Exception:
            logger.exception(
                "Qwen-VL 图片描述失败"
            )
            return ""


qwen_vl_service = QwenVLService()
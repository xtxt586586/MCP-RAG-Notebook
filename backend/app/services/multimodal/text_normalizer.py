import json
import logging
from typing import Any

from opencc import OpenCC

from app.core.config import settings


logger = logging.getLogger(__name__)

_opencc_converter = OpenCC("t2s")


def _load_aliases() -> dict[str, list[str]]:
    raw_value = (
        settings.multimodal_aliases_json
        or "{}"
    )

    try:
        parsed: Any = json.loads(raw_value)

    except json.JSONDecodeError:
        logger.warning(
            "MULTIMODAL_ALIASES_JSON 不是有效 JSON，"
            "将不使用术语别名"
        )
        return {}

    if not isinstance(parsed, dict):
        logger.warning(
            "MULTIMODAL_ALIASES_JSON 必须是对象"
        )
        return {}

    aliases: dict[str, list[str]] = {}

    for canonical, values in parsed.items():
        if not isinstance(canonical, str):
            continue

        if isinstance(values, str):
            values = [values]

        if not isinstance(values, list):
            continue

        valid_values = [
            value.strip()
            for value in values
            if isinstance(value, str)
            and value.strip()
        ]

        if valid_values:
            aliases[canonical.strip()] = (
                valid_values
            )

    return aliases


def _basic_normalize(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")
    text = text.replace("\x00", "")

    lines = [
        line.strip()
        for line in text.splitlines()
    ]

    cleaned_lines: list[str] = []
    previous_line_empty = False

    for line in lines:
        is_empty = not line

        if is_empty and previous_line_empty:
            continue

        cleaned_lines.append(line)
        previous_line_empty = is_empty

    return "\n".join(cleaned_lines).strip()


def normalize_multimodal_text(
    text: str,
) -> str:
    normalized_text = _basic_normalize(text)

    if not normalized_text:
        return ""

    normalized_text = _opencc_converter.convert(
        normalized_text
    )

    aliases = _load_aliases()

    for canonical, alias_values in aliases.items():
        for alias in alias_values:
            normalized_text = normalized_text.replace(
                alias,
                canonical,
            )

    return _basic_normalize(normalized_text)


def glossary_terms() -> list[str]:
    raw_value = (
        settings.multimodal_glossary
        or ""
    )

    return [
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    ]


def build_media_prompt() -> str:
    terms = glossary_terms()

    if not terms:
        return (
            "请准确识别中文语音和画面文字。"
        )

    return (
        "本项目可能出现以下专业术语，"
        "请优先使用这些标准写法："
        + "、".join(terms)
        + "。"
    )
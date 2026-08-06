from dataclasses import dataclass
from pathlib import Path

import pymupdf
from charset_normalizer import from_bytes


@dataclass
class ParsedUnit:
    text: str
    page_number: int


def normalize_text(text: str) -> str:
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


def decode_text_file(file_data: bytes) -> str:
    encodings = [
        "utf-8",
        "utf-8-sig",
        "gb18030",
    ]

    for encoding in encodings:
        try:
            return file_data.decode(encoding)
        except UnicodeDecodeError:
            continue

    detected = from_bytes(file_data).best()

    if detected is None:
        raise ValueError("无法识别文本文件编码")

    return str(detected)


def parse_text_file(file_data: bytes) -> list[ParsedUnit]:
    text = decode_text_file(file_data)
    text = normalize_text(text)

    if not text:
        raise ValueError("文本文件中没有可解析的内容")

    return [
        ParsedUnit(
            text=text,
            page_number=-1,
        )
    ]


def parse_pdf_file(file_data: bytes) -> list[ParsedUnit]:
    parsed_units: list[ParsedUnit] = []

    with pymupdf.open(
        stream=file_data,
        filetype="pdf",
    ) as pdf:
        for page_index, page in enumerate(pdf):
            text = page.get_text("text")
            text = normalize_text(text)

            if not text:
                continue

            parsed_units.append(
                ParsedUnit(
                    text=text,
                    page_number=page_index + 1,
                )
            )

    if not parsed_units:
        raise ValueError(
            "PDF 中没有可提取文字，可能是扫描版 PDF"
        )

    return parsed_units


def parse_document(
    file_name: str,
    file_data: bytes,
) -> tuple[list[ParsedUnit], str]:
    extension = Path(file_name).suffix.lower()

    if extension in {".txt", ".md"}:
        return parse_text_file(file_data), "plain_text"

    if extension == ".pdf":
        return parse_pdf_file(file_data), "pymupdf"

    raise ValueError(f"不支持的文件格式：{extension}")
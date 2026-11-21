from dataclasses import dataclass, field
from typing import Any
from datetime import date, datetime, time
from io import BytesIO
from pathlib import Path
from threading import Lock
import os
import tempfile

import av
from faster_whisper import WhisperModel
import numpy as np
import pymupdf
from charset_normalizer import from_bytes
from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook
from PIL import Image
from pptx import Presentation
from rapidocr_onnxruntime import RapidOCR

from app.core.config import settings
from app.services.multimodal.asr_service import (
    asr_service,
)
from app.services.multimodal.media_converter import (
    normalize_to_wav,
)
from app.services.multimodal.qwen_vl_service import (
    qwen_vl_service,
)
from app.services.multimodal.text_normalizer import (
    normalize_multimodal_text,
)
import pdfplumber


@dataclass
class ParsedUnit:
    text: str
    page_number: int
    raw_text: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )
    assets: list[dict[str, Any]] = field(
        default_factory=list
    )


_ocr_engine: RapidOCR | None = None
_ocr_engine_lock = Lock()


def get_ocr_engine() -> RapidOCR:
    global _ocr_engine

    if _ocr_engine is not None:
        return _ocr_engine

    with _ocr_engine_lock:
        if _ocr_engine is None:
            _ocr_engine = RapidOCR()

    return _ocr_engine


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


def extract_ocr_text(
    image_array: np.ndarray,
) -> str:
    result, _ = get_ocr_engine()(
        image_array
    )

    if result is None:
        return ""

    result_texts = getattr(
        result,
        "txts",
        None,
    )

    if result_texts is not None:
        texts = [
            str(text).strip()
            for text in result_texts
            if str(text).strip()
        ]

        return normalize_text(
            "\n".join(texts)
        )

    texts: list[str] = []

    for item in result:
        if isinstance(
            item,
            (list, tuple),
        ) and len(item) >= 2:
            text = str(item[1]).strip()

            if text:
                texts.append(text)

    return normalize_text(
        "\n".join(texts)
    )


def encode_frame_as_jpeg(
    image_array: np.ndarray,
) -> bytes:
    image = Image.fromarray(
        image_array
    ).convert("RGB")

    buffer = BytesIO()

    image.save(
        buffer,
        format="JPEG",
        quality=85,
    )

    return buffer.getvalue()


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
        raise ValueError(
            "无法识别文本文件编码"
        )

    return str(detected)


def parse_text_file(
    file_data: bytes,
) -> list[ParsedUnit]:
    text = decode_text_file(file_data)
    text = normalize_text(text)

    if not text:
        raise ValueError(
            "文本文件中没有可解析的内容"
        )

    return [
        ParsedUnit(
            text=text,
            page_number=-1,
        )
    ]

def render_pdf_page(
    page,
    dpi: int = 150,
) -> tuple[bytes, np.ndarray]:
    scale = dpi / 72.0

    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(
            scale,
            scale,
        ),
        alpha=False,
    )

    image_bytes = pixmap.tobytes(
        "png"
    )

    image = Image.open(
        BytesIO(image_bytes)
    ).convert("RGB")

    return (
        image_bytes,
        np.asarray(image),
    )


def parse_pdf_file(
    file_data: bytes,
) -> list[ParsedUnit]:
    parsed_units: list[ParsedUnit] = []

    try:
        pdf_document = pymupdf.open(
            stream=file_data,
            filetype="pdf",
        )

        plumber_pdf = pdfplumber.open(
            BytesIO(file_data)
        )

    except Exception as exc:
        raise ValueError(
            "PDF 文件无法打开"
        ) from exc

    try:
        for page_index, page in enumerate(
            pdf_document
        ):
            page_number = page_index + 1

            page_text = normalize_text(
                page.get_text("text")
            )

            table_parts: list[str] = []
            table_count = 0

            try:
                plumber_page = plumber_pdf.pages[
                    page_index
                ]

                tables = (
                    plumber_page.extract_tables()
                    or []
                )

                for table_index, table in enumerate(
                    tables,
                    start=1,
                ):
                    rows: list[str] = []

                    for row in table:
                        cells = [
                            normalize_text(
                                str(cell or "")
                            ).replace(
                                "\n",
                                " ",
                            )
                            for cell in row
                        ]

                        while cells and not cells[-1]:
                            cells.pop()

                        if any(cells):
                            rows.append(
                                " | ".join(cells)
                            )

                    if rows:
                        table_count += 1

                        table_parts.append(
                            f"表格 {table_index}：\n"
                            + "\n".join(rows)
                        )

            except Exception:
                table_parts = []
                table_count = 0

            image_bytes, image_array = (
                render_pdf_page(page)
            )

            ocr_text = ""

            # 页面没有可提取正文时，视为扫描页执行 OCR
            if not page_text:
                try:
                    ocr_text = extract_ocr_text(
                        image_array
                    )
                except Exception:
                    ocr_text = ""

            vision_text = ""

            has_visual_content = bool(
                page.get_images(
                    full=True
                )
                or page.get_drawings()
            )

            # 对包含图片、图表或扫描内容的页面调用 Qwen-VL
            if (
                has_visual_content
                or not page_text
            ):
                vision_text = (
                    qwen_vl_service
                    .describe_image_bytes(
                        image_bytes,
                        mime_type="image/png",
                        prompt=(
                            "请分析这一页 PDF 的内容。"
                            "如果存在图表、流程图、示意图或扫描文字，"
                            "请用准确的中文描述其含义。"
                            "如果页面中有重要文字，也请提取。"
                            "不要猜测页面中不存在的信息。"
                        ),
                    )
                )

            normalized_parts: list[str] = []
            raw_parts: list[str] = []

            if page_text:
                normalized_parts.append(
                    page_text
                )
                raw_parts.append(
                    page_text
                )

            if ocr_text:
                normalized_parts.append(
                    "扫描页 OCR：\n"
                    f"{ocr_text}"
                )
                raw_parts.append(
                    ocr_text
                )

            if table_parts:
                normalized_parts.extend(
                    table_parts
                )
                raw_parts.extend(
                    table_parts
                )

            if vision_text:
                normalized_parts.append(
                    "页面视觉描述：\n"
                    f"{vision_text}"
                )

            normalized_text = (
                normalize_multimodal_text(
                    "\n\n".join(
                        normalized_parts
                    )
                )
            )

            raw_text = normalize_text(
                "\n\n".join(raw_parts)
            )

            if not normalized_text:
                continue

            parsed_units.append(
                ParsedUnit(
                    text=normalized_text,
                    raw_text=raw_text or None,
                    page_number=page_number,
                    metadata={
                        "media_type": "pdf",
                        "page_number": page_number,
                        "table_count": table_count,
                        "ocr_enabled": bool(
                            ocr_text
                        ),
                        "vision_description_enabled": (
                            bool(vision_text)
                        ),
                        "vision_model": (
                            settings.qwen_vl_model
                            if vision_text
                            else None
                        ),
                    },
                )
            )

    finally:
        plumber_pdf.close()
        pdf_document.close()

    if not parsed_units:
        raise ValueError(
            "PDF 中没有可解析的正文、表格、扫描文字或图像内容"
        )

    return parsed_units


def parse_image_file(
    file_data: bytes,
) -> list[ParsedUnit]:
    try:
        source_image = Image.open(
            BytesIO(file_data)
        )

        image_format = (
            source_image.format or "JPEG"
        ).upper()

        image = source_image.convert("RGB")

    except Exception as exc:
        raise ValueError(
            "图片文件无法读取"
        ) from exc

    image_array = np.asarray(image)

    try:
        ocr_text = extract_ocr_text(
            image_array
        )
    except Exception as exc:
        raise ValueError(
            "图片 OCR 处理失败"
        ) from exc

    mime_type = {
        "JPEG": "image/jpeg",
        "JPG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
        "BMP": "image/bmp",
    }.get(
        image_format,
        "image/jpeg",
    )

    vision_text = (
        qwen_vl_service.describe_image_bytes(
            file_data,
            mime_type=mime_type,
            prompt=(
                "请用简洁准确的中文描述这张图片。"
                "如果图片中有文字，请同时提取主要文字。"
                "请说明图片中的人物、物体、场景和界面内容。"
                "不要猜测图片中不存在的信息。"
            ),
        )
    )

    text_parts: list[str] = []

    if ocr_text:
        text_parts.append(
            "图片文字：\n"
            f"{ocr_text}"
        )

    if vision_text:
        text_parts.append(
            "图片内容描述：\n"
            f"{vision_text}"
        )

    text = normalize_multimodal_text(
        "\n\n".join(text_parts)
    )

    if not text:
        raise ValueError(
            "图片中没有识别到文字或有效内容"
        )

    return [
        ParsedUnit(
            text=text,
            raw_text=ocr_text or None,
            page_number=-1,
            metadata={
                "media_type": "image",
                "ocr_enabled": bool(ocr_text),
                "vision_description_enabled": (
                    bool(vision_text)
                ),
                "vision_model": (
                    settings.qwen_vl_model
                    if vision_text
                    else None
                ),
            },
        )
    ]


def parse_audio_file(
    file_data: bytes,
    extension: str,
) -> list[ParsedUnit]:
    normalized_extension = extension.lower()

    if not normalized_extension.startswith("."):
        normalized_extension = (
            f".{normalized_extension}"
        )

    file_descriptor, temp_path = tempfile.mkstemp(
        suffix=normalized_extension
    )

    normalized_fd, normalized_path = tempfile.mkstemp(
        suffix=".wav"
    )

    os.close(normalized_fd)

    try:
        with os.fdopen(
            file_descriptor,
            "wb",
        ) as temp_file:
            temp_file.write(file_data)

        normalize_to_wav(
            temp_path,
            normalized_path,
        )

        asr_result = asr_service.transcribe_file(
            normalized_path
        )

    except Exception as exc:
        raise ValueError(
            f"音频语音识别失败：{exc}"
        ) from exc

    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

        try:
            os.remove(normalized_path)
        except OSError:
            pass

    if not asr_result.normalized_text:
        raise ValueError(
            "音频中没有识别到有效语音"
        )

    parsed_units: list[ParsedUnit] = []

    for segment in asr_result.segments:
        normalized_text = (
            normalize_multimodal_text(
                segment.text
            )
        )

        if not normalized_text:
            continue

        parsed_units.append(
            ParsedUnit(
                text=normalized_text,
                raw_text=segment.text,
                page_number=-1,
                metadata={
                    "media_type": "audio",
                    "start_seconds": (
                        segment.start_seconds
                    ),
                    "end_seconds": (
                        segment.end_seconds
                    ),
                    "asr_model": (
                        asr_result.model_name
                    ),
                    "asr_language": (
                        asr_result.language
                    ),
                    "average_logprob": (
                        segment.average_logprob
                    ),
                    "no_speech_prob": (
                        segment.no_speech_prob
                    ),
                    "asr_retried": (
                        asr_result.retried
                    ),
                },
            )
        )

    if not parsed_units:
        raise ValueError(
            "音频中没有识别到有效语音"
        )

    return parsed_units


def _scene_signature(
    image_array: np.ndarray,
) -> np.ndarray:
    height, width = image_array.shape[:2]

    y_indices = np.linspace(
        0,
        max(height - 1, 0),
        24,
    ).astype(int)

    x_indices = np.linspace(
        0,
        max(width - 1, 0),
        32,
    ).astype(int)

    sampled = image_array[
        np.ix_(y_indices, x_indices)
    ].astype(np.float32)

    return (
        sampled[..., 0] * 0.299
        + sampled[..., 1] * 0.587
        + sampled[..., 2] * 0.114
    )


def _scene_change_score(
    previous: np.ndarray | None,
    current: np.ndarray,
) -> float:
    if previous is None:
        return 0.0

    return float(
        np.mean(np.abs(current - previous))
        / 255.0
    )


def _fuse_video_timeline(
    parsed_units: list[ParsedUnit],
) -> list[ParsedUnit]:
    """Merge speech and keyframe events into timeline windows."""

    if not parsed_units:
        return []

    ordered_units = sorted(
        parsed_units,
        key=lambda unit: float(
            unit.metadata.get(
                "start_seconds",
                -1.0,
            )
        ),
    )

    window_seconds = max(
        0.1,
        settings.video_timeline_window_seconds,
    )
    merge_gap_seconds = max(
        0.0,
        settings.video_timeline_merge_gap_seconds,
    )

    groups: list[list[ParsedUnit]] = []
    current_group: list[ParsedUnit] = []
    current_start = 0.0
    current_end = 0.0

    for unit in ordered_units:
        start_seconds = float(
            unit.metadata.get(
                "start_seconds",
                -1.0,
            )
        )
        end_seconds = float(
            unit.metadata.get(
                "end_seconds",
                start_seconds,
            )
        )

        if start_seconds < 0:
            start_seconds = 0.0

        if end_seconds < start_seconds:
            end_seconds = start_seconds

        if not current_group:
            current_start = start_seconds
            current_end = end_seconds
            current_group.append(unit)
            continue

        exceeds_window = (
            start_seconds
            > current_start + window_seconds
        )
        exceeds_gap = (
            start_seconds
            > current_end + merge_gap_seconds
        )

        if exceeds_window or exceeds_gap:
            groups.append(current_group)
            current_group = []
            current_start = start_seconds
            current_end = end_seconds

        current_group.append(unit)
        current_end = max(
            current_end,
            end_seconds,
        )

    if current_group:
        groups.append(current_group)

    fused_units: list[ParsedUnit] = []

    for group_index, group in enumerate(
        groups
    ):
        timeline_start = min(
            float(
                unit.metadata.get(
                    "start_seconds",
                    0.0,
                )
            )
            for unit in group
        )

        timeline_end = max(
            float(
                unit.metadata.get(
                    "end_seconds",
                    unit.metadata.get(
                        "start_seconds",
                        0.0,
                    ),
                )
            )
            for unit in group
        )

        event_texts: list[str] = []
        raw_texts: list[str] = []
        event_metadata: list[dict[str, Any]] = []
        fused_assets: list[dict[str, Any]] = []
        scene_ids: set[int] = set()
        audio_count = 0
        keyframe_count = 0
        vision_enabled = False

        for unit in group:
            metadata = unit.metadata
            segment_type = str(
                metadata.get(
                    "segment_type",
                    "unknown",
                )
            )

            start_seconds = float(
                metadata.get(
                    "start_seconds",
                    0.0,
                )
            )

            end_seconds = float(
                metadata.get(
                    "end_seconds",
                    start_seconds,
                )
            )

            if segment_type == "audio":
                audio_count += 1
                label = (
                    f"[语音 {start_seconds:.1f}-"
                    f"{end_seconds:.1f} 秒]"
                )
            elif segment_type == "keyframe":
                keyframe_count += 1
                label = (
                    f"[画面 {start_seconds:.1f} 秒]"
                )
            else:
                label = (
                    f"[事件 {start_seconds:.1f} 秒]"
                )

            event_texts.append(
                f"{label}\n{unit.text}"
            )

            if unit.raw_text:
                raw_texts.append(
                    f"{label}\n{unit.raw_text}"
                )

            scene_id = metadata.get(
                "scene_id"
            )

            if isinstance(scene_id, int):
                scene_ids.add(scene_id)

            has_vision = bool(
                metadata.get(
                    "vision_description_enabled",
                    False,
                )
            )

            vision_enabled = (
                vision_enabled or has_vision
            )

            event_metadata.append(
                {
                    "segment_type": segment_type,
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                    "scene_id": scene_id,
                    "vision_description_enabled": (
                        has_vision
                    ),
                }
            )

            fused_assets.extend(
                unit.assets
            )

        fused_units.append(
            ParsedUnit(
                text=normalize_multimodal_text(
                    "\n\n".join(event_texts)
                ),
                raw_text=(
                    normalize_text(
                        "\n\n".join(raw_texts)
                    )
                    if raw_texts
                    else None
                ),
                page_number=-1,
                metadata={
                    "media_type": "video",
                    "segment_type": "timeline",
                    "timeline_fused": True,
                    "timeline_index": group_index,
                    "start_seconds": timeline_start,
                    "end_seconds": timeline_end,
                    "timeline_event_count": len(
                        group
                    ),
                    "audio_segment_count": audio_count,
                    "keyframe_count": keyframe_count,
                    "scene_ids": sorted(scene_ids),
                    "vision_description_enabled": (
                        vision_enabled
                    ),
                    "vision_model": (
                        settings.qwen_vl_model
                        if vision_enabled
                        else None
                    ),
                    "timeline_events": event_metadata,
                },
                assets=fused_assets,
            )
        )

    return fused_units


def parse_video_file(
    file_data: bytes,
    extension: str,
) -> list[ParsedUnit]:
    normalized_extension = extension.lower()

    if not normalized_extension.startswith("."):
        normalized_extension = (
            f".{normalized_extension}"
        )

    file_descriptor, temp_path = tempfile.mkstemp(
        suffix=normalized_extension
    )

    normalized_audio_fd, normalized_audio_path = (
        tempfile.mkstemp(
            suffix=".wav"
        )
    )

    os.close(normalized_audio_fd)

    parsed_units: list[ParsedUnit] = []
    seen_visual_text: set[str] = set()

    try:
        with os.fdopen(
            file_descriptor,
            "wb",
        ) as temp_file:
            temp_file.write(file_data)

        normalize_to_wav(
            temp_path,
            normalized_audio_path,
        )

        asr_result = asr_service.transcribe_file(
            normalized_audio_path
        )

        for segment in asr_result.segments:
            normalized_text = (
                normalize_multimodal_text(
                    segment.text
                )
            )

            if not normalized_text:
                continue

            parsed_units.append(
                ParsedUnit(
                    text=normalized_text,
                    raw_text=segment.text,
                    page_number=-1,
                    metadata={
                        "media_type": "video",
                        "segment_type": "audio",
                        "start_seconds": float(
                            segment.start_seconds
                        ),
                        "end_seconds": float(
                            segment.end_seconds
                        ),
                        "asr_model": (
                            asr_result.model_name
                        ),
                        "asr_language": (
                            asr_result.language
                        ),
                        "asr_retried": (
                            asr_result.retried
                        ),
                    },
                )
            )

        try:
            container = av.open(temp_path)

            try:
                if container.streams.video:
                    last_sample_time = -(
                        settings.video_keyframe_interval_seconds
                    )

                    previous_signature: (
                        np.ndarray | None
                    ) = None

                    scene_id = -1
                    scene_start_seconds = 0.0

                    for frame in container.decode(
                        video=0
                    ):
                        frame_time = float(
                            frame.time or 0.0
                        )

                        if (
                            frame_time
                            - last_sample_time
                            < settings
                            .video_keyframe_interval_seconds
                        ):
                            continue

                        last_sample_time = frame_time

                        image_array = frame.to_ndarray(
                            format="rgb24"
                        )

                        signature = _scene_signature(
                            image_array
                        )

                        change_score = (
                            _scene_change_score(
                                previous_signature,
                                signature,
                            )
                        )

                        previous_signature = signature

                        is_new_scene = (
                            scene_id < 0
                            or (
                                settings
                                .video_scene_detection_enabled
                                and change_score
                                >= settings
                                .video_scene_threshold
                            )
                        )

                        if is_new_scene:
                            scene_id += 1
                            scene_start_seconds = (
                                frame_time
                            )

                        raw_frame_text = (
                            extract_ocr_text(
                                image_array
                            )
                        )

                        frame_vision_text = (
                            qwen_vl_service
                            .describe_image_bytes(
                                encode_frame_as_jpeg(
                                    image_array
                                ),
                                mime_type="image/jpeg",
                                prompt=(
                                    "请描述这个视频关键帧的主要内容。"
                                    "如果画面中有文字，请提取文字。"
                                    "请说明人物、物体、界面和场景内容。"
                                    "不要猜测画面中不存在的信息。"
                                ),
                            )
                        )

                        frame_parts: list[str] = []

                        if raw_frame_text:
                            frame_parts.append(
                                "画面文字：\n"
                                f"{raw_frame_text}"
                            )

                        if frame_vision_text:
                            frame_parts.append(
                                "画面内容描述：\n"
                                f"{frame_vision_text}"
                            )

                        frame_text = (
                            normalize_multimodal_text(
                                "\n\n".join(
                                    frame_parts
                                )
                            )
                        )

                        if not frame_text:
                            continue

                        if frame_text in seen_visual_text:
                            continue

                        seen_visual_text.add(
                            frame_text
                        )

                        parsed_units.append(
                            ParsedUnit(
                                text=frame_text,
                                raw_text=raw_frame_text,
                                page_number=-1,
                                metadata={
                                    "media_type": "video",
                                    "segment_type": (
                                        "keyframe"
                                    ),
                                    "start_seconds": (
                                        frame_time
                                    ),
                                    "end_seconds": (
                                        frame_time
                                    ),
                                    "keyframe": True,
                                    "scene_id": scene_id,
                                    "scene_start_seconds": (
                                        scene_start_seconds
                                    ),
                                    "scene_change_score": (
                                        change_score
                                    ),
                                    "vision_description_enabled": (
                                        bool(
                                            frame_vision_text
                                        )
                                    ),
                                    "vision_model": (
                                        settings.qwen_vl_model
                                        if frame_vision_text
                                        else None
                                    ),
                                },
                                assets=[
                                    {
                                        "asset_type": (
                                            "video_keyframe"
                                        ),
                                        "data": (
                                            encode_frame_as_jpeg(
                                                image_array
                                            )
                                        ),
                                        "mime_type": (
                                            "image/jpeg"
                                        ),
                                        "metadata": {
                                            "start_seconds": (
                                                frame_time
                                            ),
                                            "end_seconds": (
                                                frame_time
                                            ),
                                            "scene_id": (
                                                scene_id
                                            ),
                                            "scene_start_seconds": (
                                                scene_start_seconds
                                            ),
                                            "scene_change_score": (
                                                change_score
                                            ),
                                        },
                                    }
                                ],
                            )
                        )

            finally:
                container.close()

        except Exception:
            if not parsed_units:
                raise

        if not parsed_units:
            raise ValueError(
                "视频中没有识别到语音或画面文字"
            )

        return _fuse_video_timeline(
            parsed_units
        )

    except Exception as exc:
        raise ValueError(
            f"视频解析失败：{exc}"
        ) from exc

    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

        try:
            os.remove(normalized_audio_path)
        except OSError:
            pass


def parse_docx_file(
    file_data: bytes,
) -> list[ParsedUnit]:
    document = DocxDocument(
        BytesIO(file_data)
    )

    content_blocks: list[str] = []

    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            text = normalize_text(block.text)

            if text:
                content_blocks.append(text)

        elif isinstance(block, Table):
            table_rows: list[str] = []

            for row in block.rows:
                cells = [
                    normalize_text(
                        cell.text
                    ).replace("\n", " ")
                    for cell in row.cells
                ]

                if any(cells):
                    table_rows.append(
                        " | ".join(cells)
                    )

            if table_rows:
                content_blocks.append(
                    "\n".join(table_rows)
                )

    text = normalize_text(
        "\n\n".join(content_blocks)
    )

    if not text:
        raise ValueError(
            "Word 文档中没有可解析的文字或表格"
        )

    return [
        ParsedUnit(
            text=text,
            page_number=-1,
        )
    ]


def parse_pptx_file(
    file_data: bytes,
) -> list[ParsedUnit]:
    presentation = Presentation(
        BytesIO(file_data)
    )

    parsed_units: list[ParsedUnit] = []

    for slide_index, slide in enumerate(
        presentation.slides,
        start=1,
    ):
        slide_parts: list[str] = []

        for shape in slide.shapes:
            if getattr(
                shape,
                "has_text_frame",
                False,
            ):
                shape_text = getattr(
                    shape,
                    "text",
                    "",
                )

                text = normalize_text(
                    shape_text
                )

                if text:
                    slide_parts.append(text)

            if getattr(
                shape,
                "has_table",
                False,
            ):
                table = getattr(
                    shape,
                    "table",
                    None,
                )

                if table is None:
                    continue

                table_rows: list[str] = []

                for row in table.rows:
                    cells = [
                        normalize_text(
                            cell.text
                        ).replace("\n", " ")
                        for cell in row.cells
                    ]

                    if any(cells):
                        table_rows.append(
                            " | ".join(cells)
                        )

                if table_rows:
                    slide_parts.append(
                        "\n".join(table_rows)
                    )

        slide_text = normalize_text(
            "\n\n".join(slide_parts)
        )

        if slide_text:
            parsed_units.append(
                ParsedUnit(
                    text=slide_text,
                    page_number=slide_index,
                )
            )

    if not parsed_units:
        raise ValueError(
            "PPT 文档中没有可解析的文字或表格"
        )

    return parsed_units


def format_excel_cell(
    value: object,
) -> str:
    if value is None:
        return ""

    if isinstance(value, datetime):
        return value.isoformat(
            sep=" "
        )

    if isinstance(value, (date, time)):
        return value.isoformat()

    return (
        str(value)
        .replace("\r\n", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\t", " ")
        .strip()
    )


def parse_xlsx_file(
    file_data: bytes,
) -> list[ParsedUnit]:
    workbook = load_workbook(
        BytesIO(file_data),
        read_only=True,
        data_only=False,
    )

    parsed_units: list[ParsedUnit] = []

    try:
        for worksheet in workbook.worksheets:
            worksheet_rows: list[str] = []

            for row in worksheet.iter_rows(
                values_only=True,
            ):
                cells = [
                    format_excel_cell(value)
                    for value in row
                ]

                while cells and not cells[-1]:
                    cells.pop()

                if any(cells):
                    worksheet_rows.append(
                        "\t".join(cells)
                    )

            if not worksheet_rows:
                continue

            worksheet_text = normalize_text(
                "\n".join(
                    [
                        f"工作表：{worksheet.title}",
                        *worksheet_rows,
                    ]
                )
            )

            parsed_units.append(
                ParsedUnit(
                    text=worksheet_text,
                    page_number=-1,
                )
            )

    finally:
        workbook.close()

    if not parsed_units:
        raise ValueError(
            "Excel 文档中没有可解析的单元格内容"
        )

    return parsed_units


def parse_document(
    file_name: str,
    file_data: bytes,
) -> tuple[list[ParsedUnit], str]:
    extension = Path(
        file_name
    ).suffix.lower()

    if extension in {".txt", ".md"}:
        return (
            parse_text_file(file_data),
            "plain_text",
        )

    if extension == ".pdf":
        return (
            parse_pdf_file(file_data),
            "pymupdf",
        )

    if extension in {
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".webp",
    }:
        return (
            parse_image_file(file_data),
            "rapidocr-qwen-vl",
        )

    if extension in {
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".m4v",
    }:
        return (
            parse_video_file(
                file_data,
                extension,
            ),
            "faster-whisper-qwen-vl-video",
        )

    if extension in {
        ".mp3",
        ".wav",
        ".m4a",
        ".aac",
        ".flac",
        ".ogg",
        ".webm",
    }:
        return (
            parse_audio_file(
                file_data,
                extension,
            ),
            "faster-whisper",
        )

    if extension == ".docx":
        return (
            parse_docx_file(file_data),
            "python-docx",
        )

    if extension == ".pptx":
        return (
            parse_pptx_file(file_data),
            "python-pptx",
        )

    if extension == ".xlsx":
        return (
            parse_xlsx_file(file_data),
            "openpyxl",
        )

    raise ValueError(
        f"不支持的文件格式：{extension}"
    )

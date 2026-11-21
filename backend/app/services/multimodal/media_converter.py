from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.core.config import settings


def _ffmpeg_command() -> str:
    executable = settings.ffmpeg_binary.strip()

    if not executable:
        executable = "ffmpeg"

    resolved = shutil.which(executable)

    if resolved is None and Path(executable).exists():
        resolved = executable

    if resolved is None:
        raise RuntimeError(
            "未找到 FFmpeg，请安装 FFmpeg 或设置 FFMPEG_BINARY"
        )

    return resolved


def normalize_to_wav(
    input_path: str,
    output_path: str,
) -> str:
    """Convert any supported media file to 16 kHz mono PCM WAV."""

    command = [
        _ffmpeg_command(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(settings.asr_sample_rate),
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        error = (completed.stderr or "").strip()
        raise RuntimeError(
            "FFmpeg 音频标准化失败"
            + (f": {error[-1000:]}" if error else "")
        )

    if not Path(output_path).exists():
        raise RuntimeError("FFmpeg 未生成标准化 WAV 文件")

    return str(output_path)

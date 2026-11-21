import logging
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from faster_whisper import WhisperModel

from app.core.config import settings
from app.services.multimodal.text_normalizer import (
    build_media_prompt,
    normalize_multimodal_text,
)
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)

@dataclass
class ASRSegment:
    text: str
    start_seconds: float
    end_seconds: float
    average_logprob: float
    no_speech_prob: float


@dataclass
class ASRResult:
    raw_text: str
    normalized_text: str
    model_name: str
    language: str | None
    duration_seconds: float
    average_logprob: float
    average_no_speech_prob: float
    retried: bool
    segments: list[ASRSegment] = field(
        default_factory=list
    )


class ASRService:
    def __init__(self) -> None:
        self._models: dict[
            str,
            WhisperModel,
        ] = {}

        self._model_lock = Lock()

    def _get_model(
        self,
        model_name: str,
    ) -> WhisperModel:
        if model_name in self._models:
            return self._models[model_name]

        with self._model_lock:
            if model_name not in self._models:
                logger.info(
                    "正在加载 ASR 模型：%s",
                    model_name,
                )

                self._models[model_name] = (
                    WhisperModel(
                        model_name,
                        device=settings.asr_device,
                        compute_type=(
                            settings.asr_compute_type
                        ),
                    )
                )

                logger.info(
                    "ASR 模型加载完成：%s",
                    model_name,
                )

        return self._models[model_name]

    @staticmethod
    def _transcribe_once(
        *,
        model: WhisperModel,
        file_path: str,
    ) -> ASRResult:
        segments, info = model.transcribe(
            file_path,
            language="zh",
            vad_filter=True,
            beam_size=5,
            initial_prompt=(
                build_media_prompt()
            ),
        )

        segment_list = list(segments)

        raw_texts: list[str] = []
        logprob_values: list[float] = []
        no_speech_values: list[float] = []
        transcription_segments: list[ASRSegment] = []

        for segment in segment_list:
            segment_text = segment.text.strip()

            if not segment_text:
                continue

            average_logprob = float(
                segment.avg_logprob
                if segment.avg_logprob is not None
                else -10.0
            )

            no_speech_prob = float(
                segment.no_speech_prob
                if segment.no_speech_prob is not None
                else 1.0
            )

            raw_texts.append(segment_text)
            logprob_values.append(average_logprob)
            no_speech_values.append(no_speech_prob)

            transcription_segments.append(
                ASRSegment(
                    text=segment_text,
                    start_seconds=float(
                        segment.start
                    ),
                    end_seconds=float(
                        segment.end
                    ),
                    average_logprob=average_logprob,
                    no_speech_prob=no_speech_prob,
                )
            )

        raw_text = "\n".join(raw_texts)

        average_logprob = (
            sum(logprob_values)
            / len(logprob_values)
            if logprob_values
            else -10.0
        )

        average_no_speech_prob = (
            sum(no_speech_values)
            / len(no_speech_values)
            if no_speech_values
            else 1.0
        )

        return ASRResult(
            raw_text=raw_text,
            normalized_text=(
                normalize_multimodal_text(
                    raw_text
                )
            ),
            model_name=(
                model.model_name
                if hasattr(model, "model_name")
                else "unknown"
            ),
            language=getattr(
                info,
                "language",
                None,
            ),
            duration_seconds=float(
                getattr(
                    info,
                    "duration",
                    0.0,
                )
                or 0.0
            ),
            average_logprob=average_logprob,
            average_no_speech_prob=(
                average_no_speech_prob
            ),
            retried=False,
            segments=transcription_segments,
        )

    @staticmethod
    def _is_low_quality(
        result: ASRResult,
    ) -> bool:
        return (
            result.average_logprob
            < settings.asr_quality_logprob_threshold
            or result.average_no_speech_prob
            > settings.asr_quality_no_speech_threshold
        )

    @staticmethod
    def _quality_score(
        result: ASRResult,
    ) -> float:
        return (
            result.average_logprob
            - result.average_no_speech_prob
        )

    def _transcribe_sync(
        self,
        *,
        file_path: str,
    ) -> ASRResult:
        primary_model_name = (
            settings.asr_primary_model
        )

        primary_model = self._get_model(
            primary_model_name
        )

        primary_result = (
            self._transcribe_once(
                model=primary_model,
                file_path=file_path,
            )
        )

        if (
            not self._is_low_quality(
                primary_result
            )
            or (
                settings.asr_fallback_model
                == primary_model_name
            )
        ):
            primary_result.model_name = (
                primary_model_name
            )
            return primary_result

        logger.warning(
            "ASR 结果质量较低，使用备用模型重试："
            "model=%s average_logprob=%.3f "
            "no_speech_prob=%.3f",
            primary_model_name,
            primary_result.average_logprob,
            primary_result.average_no_speech_prob,
        )

        fallback_model_name = (
            settings.asr_fallback_model
        )

        fallback_model = self._get_model(
            fallback_model_name
        )

        fallback_result = (
            self._transcribe_once(
                model=fallback_model,
                file_path=file_path,
            )
        )

        primary_result.model_name = (
            primary_model_name
        )

        fallback_result.model_name = (
            fallback_model_name
        )
        fallback_result.retried = True

        if (
            self._quality_score(fallback_result)
            > self._quality_score(primary_result)
        ):
            return fallback_result

        primary_result.retried = True
        return primary_result

    def transcribe_file(
        self,
        file_path: str,
    ) -> ASRResult:
        resolved_path = str(
            Path(file_path).resolve()
        )

        if not os.path.exists(resolved_path):
            raise FileNotFoundError(
                resolved_path
            )

        return self._transcribe_sync(
            file_path=resolved_path
        )


asr_service = ASRService()
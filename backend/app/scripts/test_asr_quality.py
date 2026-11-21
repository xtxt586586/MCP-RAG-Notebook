from app.core.config import settings
from app.services.multimodal.asr_service import (
    ASRResult,
    ASRService,
)


def build_result(
    *,
    model_name: str,
    average_logprob: float,
    average_no_speech_prob: float,
) -> ASRResult:
    return ASRResult(
        raw_text="Milvus 是一个向量数据库。",
        normalized_text=(
            "Milvus 是一个向量数据库。"
        ),
        model_name=model_name,
        language="zh",
        duration_seconds=5.0,
        average_logprob=average_logprob,
        average_no_speech_prob=(
            average_no_speech_prob
        ),
        retried=False,
    )


def main() -> None:
    service = ASRService()

    primary_model_name = (
        settings.asr_primary_model
    )
    fallback_model_name = (
        settings.asr_fallback_model
    )

    primary_result = build_result(
        model_name=primary_model_name,
        average_logprob=-2.0,
        average_no_speech_prob=0.8,
    )

    fallback_result = build_result(
        model_name=fallback_model_name,
        average_logprob=-0.3,
        average_no_speech_prob=0.05,
    )

    service._get_model = (
        lambda model_name: model_name
    )

    service._transcribe_once = (
        lambda *, model, file_path: (
            primary_result
            if model == primary_model_name
            else fallback_result
        )
    )

    result = service._transcribe_sync(
        file_path=__file__
    )

    assert result.retried is True
    assert result.model_name == (
        fallback_model_name
    )
    assert result.average_logprob == (
        fallback_result.average_logprob
    )

    print("ASR 低质量自动重试测试通过")
    print("首次模型：", primary_model_name)
    print("备用模型：", fallback_model_name)
    print("最终使用模型：", result.model_name)


if __name__ == "__main__":
    main()
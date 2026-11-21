# 读取项目根目录的 .env
from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "MCP-RAG-Notebook"
    app_version: str = "0.1.0"

    database_url: str

    redis_url: str = (
        "redis://localhost:6379/0"
    )

    milvus_uri: str = (
        "http://localhost:19530"
    )

    milvus_collection: str = (
        "knowledge_chunks"
    )

    minio_endpoint: str = (
        "localhost:9000"
    )

    minio_root_user: str
    minio_root_password: str

    minio_bucket: str = "rag-files"
    minio_secure: bool = False

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    embedding_model: str = "BAAI/bge-m3"
    embedding_batch_size: int = 4
    embedding_max_length: int = 1024
    embedding_offline: bool = True
    graph_auto_extract_enabled: bool = True
    model_warmup_enabled: bool = True

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    auth_cookie_secure: bool = False
    # Comma-separated browser origins allowed to send credentialed requests.
    cors_allowed_origins: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "http://localhost:5173,"
        "http://127.0.0.1:5173"
    )

    deepseek_api_key: str
    deepseek_base_url: str = (
        "https://api.deepseek.com"
    )
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = 120.0
    deepseek_connect_timeout_seconds: float = 3.0
    deepseek_max_retries: int = 4
    deepseek_retry_backoff_seconds: float = 0.5
    # The container's inherited proxy may be unavailable; direct egress is
    # the default and can be opted into with DEEPSEEK_TRUST_ENV=true.
    deepseek_trust_env: bool = False

    rag_default_top_k: int = 5
    rag_max_context_chars: int = 12000
    rag_min_relevance_score: float = 0.5
    rag_query_rewrite_enabled: bool = True
    rag_query_rewrite_timeout_seconds: float = 8.0
    rag_route_score_margin: float = 0.03

    # A worker that has not updated its ingestion task within this window is
    # considered stale and can be marked failed/cleaned up by the API.
    ingestion_stale_after_seconds: int = 1800

    asr_primary_model: str = "base"
    asr_fallback_model: str = "small"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"

    asr_quality_logprob_threshold: float = -1.0
    asr_quality_no_speech_threshold: float = 0.6

    ffmpeg_binary: str = "ffmpeg"
    asr_sample_rate: int = 16000

    multimodal_glossary: str = (
        "Milvus,BGE-M3,MinIO,"
        "PostgreSQL,Redis,Celery,"
        "FastAPI,Whisper,RapidOCR"
    )

    multimodal_aliases_json: str = "{}"

    ocr_min_score: float = 0.5

    video_keyframe_interval_seconds: float = 2.0
    video_scene_detection_enabled: bool = True
    video_scene_threshold: float = 0.18
    video_timeline_window_seconds: float = 8.0
    video_timeline_merge_gap_seconds: float = 1.5

    reranker_model: str = (
        "BAAI/bge-reranker-v2-m3"
    )
    reranker_batch_size: int = 8
    reranker_enabled: bool = True
    reranker_timeout_seconds: float = 5.0

    mcp_servers_config: str = str(
        PROJECT_ROOT
        / "mcp_servers"
        / "servers.json"
    )
    # Dynamic registry definitions can launch arbitrary processes. Enable only
    # on a trusted, single-user installation; this is not an administrator role.
    mcp_dynamic_registry_enabled: bool = False

    mcp_agent_allowed_tools: str = (
        "rag_notebook:create_note,"
        "rag_notebook:search_notes,"
        "rag_notebook:summarize_document,"
        "filesystem:list_allowed_directories,"
        "filesystem:list_directory,"
        "filesystem:read_text_file,"
        "filesystem:search_files,"
        "fetch:fetch"
    )

    mcp_agent_max_steps: int = 4
    # Bound the amount of persisted conversation context sent to the model.
    agent_history_max_turns: int = 8
    mcp_tool_result_max_chars: int = 12000

    mcp_client_allowed_tools: str = (
        "rag_notebook:backend_health,"
        "rag_notebook:search_knowledge_base,"
        "rag_notebook:ask_knowledge_base,"
        "rag_notebook:create_note,"
        "rag_notebook:search_notes,"
        "rag_notebook:summarize_document,"
        "memory:create_entities,"
        "memory:create_relations,"
        "memory:add_observations,"
        "memory:delete_entities,"
        "memory:delete_observations,"
        "memory:delete_relations,"
        "memory:read_graph,"
        "memory:search_nodes,"
        "memory:open_nodes,"
        "filesystem:list_allowed_directories,"
        "filesystem:list_directory,"
        "filesystem:read_text_file,"
        "filesystem:search_files,"
        "filesystem:get_file_info,"
        "fetch:fetch"
    )

    celery_broker_url: str = (
        "redis://localhost:6379/0"
    )

    celery_result_backend: str = (
        "redis://localhost:6379/1"
    )

    celery_task_always_eager: bool = False

    mcp_tool_timeout_seconds: float = 180.0
    mcp_tool_retry_attempts: int = 2
    mcp_tool_retry_backoff_seconds: float = 1.0

    observability_slow_request_ms: float = 1000.0

    # Shared secret used by the host-side MCP server to submit audit events.
    mcp_audit_token: str = ""

    qwen_vl_enabled: bool = False
    qwen_vl_provider: str = "dashscope"
    qwen_vl_model: str = "qwen-vl-plus"
    qwen_vl_base_url: str = (
        "https://dashscope.aliyuncs.com/"
        "compatible-mode/v1"
    )
    qwen_vl_api_key: str = ""
    qwen_vl_timeout_seconds: float = 60.0

    mcp_agent_allowed_tools: str = (
        "rag_notebook:create_note,"
        "rag_notebook:search_notes,"
        "rag_notebook:summarize_document,"
        "memory:create_entities,"
        "memory:create_relations,"
        "memory:add_observations,"
        "memory:delete_entities,"
        "memory:delete_observations,"
        "memory:delete_relations,"
        "memory:read_graph,"
        "memory:search_nodes,"
        "memory:open_nodes,"
        "filesystem:list_allowed_directories,"
        "filesystem:list_directory,"
        "filesystem:read_text_file,"
        "filesystem:search_files,"
        "fetch:fetch"
    )


settings = Settings()

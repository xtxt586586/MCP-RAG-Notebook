#读取根目录的 .env
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "MCP-RAG-Notebook"
    app_version: str = "0.1.0"

    database_url: str

    redis_url: str = "redis://localhost:6379/0"

    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "knowledge_chunks"

    minio_endpoint: str = "localhost:9000"
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

    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = 120.0

    rag_default_top_k: int = 5
    rag_max_context_chars: int = 12000

    mcp_servers_config: str = str(
        PROJECT_ROOT
        / "mcp_servers"
        / "servers.json"
    )

    mcp_agent_allowed_tools: str = (
        "rag_notebook:search_knowledge_base,"
        "filesystem:list_allowed_directories,"
        "filesystem:list_directory,"
        "filesystem:read_text_file,"
        "filesystem:search_files,"
        "fetch:fetch"
    )

    mcp_agent_max_steps: int = 4
    mcp_tool_result_max_chars: int = 12000

    mcp_client_allowed_tools: str = (
        "rag_notebook:backend_health,"
        "rag_notebook:search_knowledge_base,"
        "filesystem:list_allowed_directories,"
        "filesystem:list_directory,"
        "filesystem:read_text_file,"
        "filesystem:search_files,"
        "filesystem:get_file_info,"
        "fetch:fetch"
    )

    mcp_tool_timeout_seconds: float = 180.0

settings = Settings()

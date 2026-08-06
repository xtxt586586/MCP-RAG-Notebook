#将基础设施依赖（数据库、缓存、向量库、对象存储）的配置统一对外暴露
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

settings = Settings()

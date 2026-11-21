import asyncio
import logging
import secrets

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from pymilvus import MilvusClient

from app.core.config import settings
from app.core.observability import observe_request, request_metrics
from app.api.dependencies import (
    ACCESS_TOKEN_COOKIE,
    CSRF_TOKEN_COOKIE,
    CSRF_TOKEN_HEADER,
)
from app.core.database import engine
from app.api.router import api_router
from app.services.embedding.bge_m3_service import (
    bge_m3_embedding_service,
)
from app.services.reranking.bge_reranker_service import (
    bge_reranker_service,
)
from starlette.concurrency import run_in_threadpool


logger = logging.getLogger(__name__)


class UTF8JSONResponse(JSONResponse):
    """Declare UTF-8 explicitly for Windows PowerShell and other clients."""

    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="MCP-RAG-Notebook API",
    version="0.1.0",
    default_response_class=UTF8JSONResponse,
)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.cors_allowed_origins.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def csrf_protection(request, call_next):
    """Validate the double-submit token for cookie-authenticated writes."""
    unsafe_method = request.method.upper() not in {
        "GET",
        "HEAD",
        "OPTIONS",
        "TRACE",
    }
    exempt_path = request.url.path in {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/refresh",
    }

    if (
        unsafe_method
        and not exempt_path
        and request.cookies.get(ACCESS_TOKEN_COOKIE)
    ):
        csrf_cookie = request.cookies.get(CSRF_TOKEN_COOKIE)
        csrf_header = request.headers.get(CSRF_TOKEN_HEADER)
        if (
            not csrf_cookie
            or not csrf_header
            or not secrets.compare_digest(csrf_cookie, csrf_header)
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF Token 无效或缺失"},
            )

    return await call_next(request)

app.middleware("http")(observe_request)


async def _warmup_models() -> None:
    """Load local retrieval models after startup so the first query is fast."""
    try:
        await run_in_threadpool(bge_m3_embedding_service._get_model)
        if settings.reranker_enabled:
            await run_in_threadpool(bge_reranker_service._get_model)
        logger.info("RAG 检索模型预热完成")
    except Exception:
        # A failed warm-up must not make the API unavailable; the services
        # will retry lazy loading when a knowledge query arrives.
        logger.exception("RAG 检索模型预热失败，将按需加载")


@app.on_event("startup")
async def start_model_warmup() -> None:
    if settings.model_warmup_enabled:
        asyncio.create_task(_warmup_models())


@app.get("/health", tags=["系统"])
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "MCP-RAG-Notebook backend",
    }


@app.get("/health/metrics", tags=["系统"])
async def metrics_health_check() -> dict[str, object]:
    return {
        "status": "ok",
        "metrics": request_metrics.snapshot(),
    }


@app.get("/health/database", tags=["系统"])
async def database_health_check() -> dict[str, str]:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "postgresql",
    }


@app.get("/health/milvus", tags=["系统"])
def milvus_health_check() -> dict:
    client = MilvusClient(uri=settings.milvus_uri)

    try:
        collections = client.list_collections()

        return {
            "status": "ok",
            "database": "milvus",
            "collection": settings.milvus_collection,
            "collection_exists": (
                settings.milvus_collection in collections
            ),
        }
    finally:
        client.close()

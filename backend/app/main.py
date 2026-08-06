from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from pymilvus import MilvusClient

from app.core.config import settings
from app.core.database import engine
from app.api.router import api_router

app = FastAPI(
    title="MCP-RAG-Notebook API",
    version="0.1.0",
)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["系统"])
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "MCP-RAG-Notebook backend",
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
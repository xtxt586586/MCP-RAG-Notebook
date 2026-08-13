import logging
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Document, KnowledgeBase
from app.services.retrieval.hybrid_search_service import (
    hybrid_search_service,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/search",
    tags=["检索"],
)


class SearchRequest(BaseModel):
    user_id: UUID
    knowledge_base_id: UUID
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Literal["dense", "sparse", "hybrid"] = "hybrid"

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("查询内容不能为空")
        return normalized_value


class SearchResult(BaseModel):
    rank: int
    score: float
    chunk_id: str
    content: str
    document_id: str
    chunk_index: int
    file_name: str | None = None
    page_number: int = 0
    source_type: str = "text"
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    mode: Literal["dense", "sparse", "hybrid"]
    top_k: int
    count: int
    results: list[SearchResult]


@router.post("", response_model=SearchResponse)
async def search_knowledge_base(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    knowledge_base_result = await db.execute(
        select(KnowledgeBase.id).where(
            KnowledgeBase.id == request.knowledge_base_id,
            KnowledgeBase.user_id == request.user_id,
        )
    )

    if knowledge_base_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=404,
            detail="知识库不存在或不属于当前用户",
        )

    try:
        results = await hybrid_search_service.search(
            user_id=str(request.user_id),
            knowledge_base_id=str(request.knowledge_base_id),
            query=request.query,
            mode=request.mode,
            top_k=request.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("知识库检索失败")
        raise HTTPException(
            status_code=500,
            detail="知识库检索失败",
        ) from exc

    document_ids = {
        UUID(item["document_id"])
        for item in results
        if item.get("document_id")
    }

    if document_ids:
        documents_result = await db.execute(
            select(Document.id, Document.file_name).where(
                Document.id.in_(document_ids),
                Document.knowledge_base_id == request.knowledge_base_id,
            )
        )
        file_names = {
            str(document_id): file_name
            for document_id, file_name in documents_result.all()
        }

        for item in results:
            item["file_name"] = file_names.get(
                item["document_id"],
                item.get("file_name"),
            )

    return SearchResponse(
        query=request.query,
        mode=request.mode,
        top_k=request.top_k,
        count=len(results),
        results=results,
    )

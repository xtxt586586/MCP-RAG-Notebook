#知识库检索路由模块
import logging
from time import perf_counter
from typing import Any, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from pydantic import (
    BaseModel,
    Field,
    field_validator,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.core.database import get_db
from app.models import Document
from app.services.retrieval.hybrid_search_service import (
    hybrid_search_service,
)
from app.services.knowledge_base_service import (
    get_current_user_knowledge_base,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/search",
    tags=["检索"],
)


class SearchRequest(BaseModel):
    knowledge_base_id: UUID
    query: str = Field(
        min_length=1,
        max_length=2000,
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
    )
    mode: Literal[
        "dense",
        "sparse",
        "hybrid",
    ] = "hybrid"

    @field_validator("query")
    @classmethod
    def validate_query(
        cls,
        value: str,
    ) -> str:
        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError(
                "查询内容不能为空"
            )

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
    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class SearchResponse(BaseModel):
    query: str
    mode: Literal[
        "dense",
        "sparse",
        "hybrid",
    ]
    top_k: int
    count: int
    results: list[SearchResult]


@router.post(
    "",
    response_model=SearchResponse,
)
async def search_knowledge_base(
    request: SearchRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    request_started_at = perf_counter()
    validation_started_at = request_started_at
    await get_current_user_knowledge_base(
        db=db,
        user_id=current_user.id,
        requested_id=request.knowledge_base_id,
    )
    validation_ms = (perf_counter() - validation_started_at) * 1000

    try:
        retrieval_started_at = perf_counter()
        results = (
            await hybrid_search_service.search(
                user_id=str(current_user.id),
                knowledge_base_id=str(
                    request.knowledge_base_id
                ),
                query=request.query,
                mode=request.mode,
                top_k=request.top_k,
            )
        )
        retrieval_ms = (perf_counter() - retrieval_started_at) * 1000

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "知识库检索失败："
            "user_id=%s knowledge_base_id=%s",
            current_user.id,
            request.knowledge_base_id,
        )

        raise HTTPException(
            status_code=500,
            detail="知识库检索失败",
        ) from exc

    document_ids: set[UUID] = set()

    for item in results:
        document_id = item.get("document_id")

        if not document_id:
            continue

        try:
            document_ids.add(
                UUID(document_id)
            )
        except ValueError:
            logger.warning(
                "Milvus 返回了无效文档 ID：%s",
                document_id,
            )

    metadata_started_at = perf_counter()
    if document_ids:
        documents_result = await db.execute(
            select(
                Document.id,
                Document.file_name,
            ).where(
                Document.id.in_(document_ids),
                Document.knowledge_base_id
                == request.knowledge_base_id,
            )
        )

        file_names = {
            str(document_id): file_name
            for document_id, file_name
            in documents_result.all()
        }

        for item in results:
            item["file_name"] = (
                file_names.get(
                    item["document_id"],
                    item.get("file_name"),
                )
            )

    metadata_ms = (perf_counter() - metadata_started_at) * 1000
    logger.info(
        "知识库检索接口耗时 validation_ms=%.2f retrieval_ms=%.2f "
        "metadata_ms=%.2f total_ms=%.2f results=%d",
        validation_ms,
        retrieval_ms,
        metadata_ms,
        (perf_counter() - request_started_at) * 1000,
        len(results),
    )

    return SearchResponse(
        query=request.query,
        mode=request.mode,
        top_k=request.top_k,
        count=len(results),
        results=results,
    )

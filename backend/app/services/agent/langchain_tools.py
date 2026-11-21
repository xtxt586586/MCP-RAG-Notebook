import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel,Field,create_model
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note, ReviewEvent, ReviewRecord
from app.services.mcp.client_manager import mcp_client_manager
from app.services.mcp.tool_catalog import mcp_tool_catalog
from app.services.retrieval.hybrid_search_service import (
    hybrid_search_service,
)
from app.services.review_service import get_next_interval


def _json_text(value:Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        default=str,
    )


async def _search_notes(
        *,
        db:AsyncSession,
        user_id: str,
        knowledge_base_id: str,
        query: str,
        limit: int = 5,
) -> str:
    user_uuid = UUID(user_id)
    knowledge_base_uuid = UUID(knowledge_base_id)
    bounded_limit = max(1, min(limit, 10))

    notes_by_id: dict[UUID, Note] = {}
    try:
        semantic_results = await hybrid_search_service.search(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            query=query,
            top_k=bounded_limit,
            source="notes",
        )
        semantic_ids = [
            UUID(str(item["document_id"]))
            for item in semantic_results
            if item.get("document_id")
        ]
        if semantic_ids:
            result = await db.execute(
                select(Note).where(
                    Note.id.in_(semantic_ids),
                    Note.user_id == user_uuid,
                    Note.knowledge_base_id == knowledge_base_uuid,
                )
            )
            notes_by_id = {
                note.id: note
                for note in result.scalars().all()
            }
            notes = [
                notes_by_id[note_id]
                for note_id in semantic_ids
                if note_id in notes_by_id
            ]
        else:
            notes = []
    except Exception:
        notes = []

    if not notes:
        statement = (
            select(Note)
            .where(
                Note.user_id == user_uuid,
                Note.knowledge_base_id == knowledge_base_uuid,
                or_(
                    Note.title.ilike(f"%{query}%"),
                    Note.content.ilike(f"%{query}%"),
                ),
            )
            .order_by(Note.created_at.desc())
            .limit(bounded_limit)
        )
        result = await db.execute(statement)
        notes = result.scalars().all()

    return _json_text(
        {
            "query":query,
            "notes":[
                {
                    "id": str(note.id),
                    "title": note.title,
                    "content": note.content[:2000],
                    "update_at": note.updated_at,
                }
                for note in notes
            ],
        }
    )


async def _note_stats(
        *,
        db: AsyncSession,
        user_id: str,
        knowledge_base_id: str,
) -> str:
    user_uuid = UUID(user_id)
    knowledge_base_uuid = UUID(knowledge_base_id)

    total_result = await db.execute(
        select(func.count(Note.id)).where(
            Note.user_id == user_uuid,
            Note.knowledge_base_id == knowledge_base_uuid,
        )
    )

    total = int(total_result.scalar_one() or 0)

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    recent_result = await db.execute(
        select(func.count(Note.id)).where(
            Note.user_id == user_uuid,
            Note.knowledge_base_id == knowledge_base_uuid,
            Note.created_at >= cutoff,
        )
    )

    recent = int(recent_result.scalar_one() or 0)

    return _json_text({
        "knowledge_base_id": knowledge_base_id,
        "total": total,
        "created_in_last_30_days": recent,
    })


async def _today_reviews(
        *,
        db: AsyncSession,
        user_id: str,
        knowledge_base_id: str,
        limit: int = 10,
) -> str:
    user_uuid = UUID(user_id)
    knowledge_base_uuid = UUID(knowledge_base_id)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(ReviewRecord, Note)
        .join(Note, Note.id == ReviewRecord.note_id)
        .where(
            ReviewRecord.user_id == user_uuid,
            Note.user_id == user_uuid,
            Note.knowledge_base_id == knowledge_base_uuid,
            ReviewRecord.next_review_at <= now,
        )
        .order_by(ReviewRecord.next_review_at.asc())
        .limit(max(1, min(limit, 20)))
    )

    return _json_text({
        "items": [
            {
                "review_id": str(record.id),
                "note_id": str(note.id),
                "title": note.title,
                "content_preview": note.content[:240],
                "review_count": record.review_count,
                "interval_days": record.interval_days,
                "next_review_at": record.next_review_at,
            }
            for record, note in result.all()
        ],
    })


async def _mark_note_reviewed(
        *,
        db: AsyncSession,
        user_id: str,
        knowledge_base_id: str,
        note_id: str,
) -> str:
    user_uuid = UUID(user_id)
    knowledge_base_uuid = UUID(knowledge_base_id)
    note_uuid = UUID(note_id)

    result = await db.execute(
        select(ReviewRecord)
        .join(Note, Note.id == ReviewRecord.note_id)
        .where(
            ReviewRecord.note_id == note_uuid,
            ReviewRecord.user_id == user_uuid,
            Note.user_id == user_uuid,
            Note.knowledge_base_id == knowledge_base_uuid,
        )
    )

    record = result.scalar_one_or_none()

    if record is None:
        return _json_text({
            "success": False,
            "message": "回顾记录不存在或不属于当前知识库",
        })

    now = datetime.now(timezone.utc)
    record.review_count += 1
    record.interval_days = get_next_interval(record.review_count)
    record.last_reviewed_at = now
    record.next_review_at = now.replace(
        microsecond=0,
    )
    record.next_review_at += timedelta(days=record.interval_days)

    db.add(
        ReviewEvent(
            note_id=note_uuid,
            user_id=user_uuid,
            review_count=record.review_count,
            interval_days=record.interval_days,
            reviewed_at=now,
        )
    )

    await db.commit()

    return _json_text({
        "success": True,
        "note_id": note_id,
        "review_count": record.review_count,
        "interval_days": record.interval_days,
        "next_review_at": record.next_review_at,
    })


async def _related_notes(
        *,
        db: AsyncSession,
        user_id: str,
        knowledge_base_id: str,
        note_id: str,
        top_k: int = 3,
) -> str:
    user_uuid = UUID(user_id)
    knowledge_base_uuid = UUID(knowledge_base_id)
    note_uuid = UUID(note_id)

    note_result = await db.execute(
        select(Note).where(
            Note.id == note_uuid,
            Note.user_id == user_uuid,
            Note.knowledge_base_id == knowledge_base_uuid,
        )
    )
    note = note_result.scalar_one_or_none()

    if note is None:
        return _json_text({"note_id": note_id, "items": []})

    items: list[dict[str, Any]] = []
    try:
        note_results = await hybrid_search_service.search(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            query=note.content[:500] or note.title,
            top_k=max(1, min(top_k + 1, 10)),
            source="notes",
        )
        related_ids = [
            UUID(str(item["document_id"]))
            for item in note_results
            if item.get("document_id")
            and str(item["document_id"]) != note_id
        ]
        if related_ids:
            related_result = await db.execute(
                select(Note).where(
                    Note.id.in_(related_ids),
                    Note.user_id == user_uuid,
                    Note.knowledge_base_id == knowledge_base_uuid,
                )
            )
            related_map = {
                item.id: item
                for item in related_result.scalars().all()
            }
            items = [
                {
                    "source": "note",
                    "id": str(related_id),
                    "title": related_map[related_id].title,
                    "content_preview": related_map[related_id].content[:240],
                }
                for related_id in related_ids
                if related_id in related_map
            ]
    except Exception:
        # Keyword fallback keeps related suggestions available while the
        # vector service is warming up or temporarily unavailable.
        pattern = (note.title or note.content[:80]).strip()
        note_result = await db.execute(
            select(Note)
            .where(
                Note.id != note_uuid,
                Note.user_id == user_uuid,
                Note.knowledge_base_id == knowledge_base_uuid,
                or_(
                    Note.title.ilike(f"%{pattern[:80]}%"),
                    Note.content.ilike(f"%{pattern[:80]}%"),
                ),
            )
            .order_by(Note.updated_at.desc())
            .limit(max(1, min(top_k, 10)))
        )
        items = [
            {
                "source": "note",
                "id": str(item.id),
                "title": item.title,
                "content_preview": item.content[:240],
            }
            for item in note_result.scalars().all()
        ]

    try:
        knowledge_results = await hybrid_search_service.search(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            query=note.content[:500] or note.title,
            top_k=max(1, min(top_k, 10)),
            source="documents",
        )
        items.extend(
            {
                "source": "knowledge_base",
                "document_id": item.get("document_id"),
                "file_name": item.get("file_name"),
                "content_preview": str(item.get("content", ""))[:240],
                "score": item.get("score"),
            }
            for item in knowledge_results
        )
    except Exception:
        # Related note suggestions remain useful if vector search is offline.
        pass

    return _json_text({"note_id": note_id, "items": items[: max(1, min(top_k * 2, 20))]})


def build_project_tools(
        *,
        db: AsyncSession,
        user_id: str,
        knowledge_base_id: str,
) -> list[BaseTool]:
    class SearchNotesArgs(BaseModel):
        query:str = Field(
            description="要搜索的笔记关键词",
        )

    class EmptyArgs(BaseModel):
        pass

    class TodayReviewsArgs(BaseModel):
        limit: int = Field(default=10, ge=1, le=20, description="最多返回的待回顾笔记数量")

    class MarkReviewedArgs(BaseModel):
        note_id: str = Field(description="要标记为已回顾的笔记 ID")

    class RelatedNotesArgs(BaseModel):
        note_id: str = Field(description="要查找关联内容的笔记 ID")
        top_k: int = Field(default=3, ge=1, le=10, description="每类最多返回的关联内容数量")

    @tool(
        "project_search_notes",
        description="搜索当前用户当前知识库下的历史笔记。",
        args_schema=SearchNotesArgs,
    )
    async def search_notes(query: str, limit: int = 5) -> str:
        return await _search_notes(
            db=db,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            query=query,
            limit=limit,
        )

    @tool(
        "project_get_note_stats",
        description="获取当前知识库的笔记数量统计。",
        args_schema=EmptyArgs,
    )
    async def note_stats() -> str:
        return await _note_stats(
            db=db,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
        )

    @tool(
        "project_get_today_reviews",
        description="获取当前知识库中今天需要复习的笔记。",
        args_schema=TodayReviewsArgs,
    )
    async def today_reviews(limit: int = 10) -> str:
        return await _today_reviews(
            db=db,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            limit=limit,
        )

    @tool(
        "project_mark_note_reviewed",
        description="将当前知识库中的一篇笔记标记为已复习。",
        args_schema=MarkReviewedArgs,
    )
    async def mark_reviewed(note_id: str) -> str:
        return await _mark_note_reviewed(
            db=db,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            note_id=note_id,
        )

    @tool(
        "project_get_related_notes",
        description="查找一篇笔记关联的其他笔记和知识库资料。",
        args_schema=RelatedNotesArgs,
    )
    async def related_notes(note_id: str, top_k: int = 3) -> str:
        return await _related_notes(
            db=db,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            note_id=note_id,
            top_k=top_k,
        )

    @tool(
        "project_what_time_is_now",
        description="获取当前日期和时间。",
        args_schema=EmptyArgs,
    )
    async def current_time() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    return [
        search_notes,
        note_stats,
        today_reviews,
        mark_reviewed,
        related_notes,
        current_time,
    ]


def _schema_type(value: Any) -> Any:
    if value == "string":
        return str
    if value == "integer":
        return int
    if value == "number":
        return float
    if value == "boolean":
        return bool
    if value == "array":
        return list[Any]
    if value == "object":
        return dict[str,Any]

    return Any


def _build_args_model(
        name: str,
        schema: dict[str, Any],
) -> type[BaseModel]:
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])

    fields: dict[str,tuple[Any,Any]] = {}

    for field_name,field_schema in properties.items():
        field_type = _schema_type(
            field_schema.get("type"),
        )
        description = field_schema.get(
            "description",
            "",
        )

        if field_name in required:
            fields[field_name] = (
                field_type,
                Field(
                    ...,
                    description=description,
                ),
            )
        else:
            fields[field_name] = (
                field_type | None,
                Field(
                    default=None,
                    description=description,
                ),
            )
    return create_model(
        name,
        **fields,
    )


async def build_mcp_tools(
        *,
        user_id: str,
        knowledge_base_id: str,
        access_token: str | None = None,
) -> list[BaseTool]:
    raw_tools,tool_mapping = (
        await mcp_tool_catalog.build_catalog()
    )

    result: list[BaseTool] = []

    for raw_tool in raw_tools:
        function = raw_tool["function"]
        function_name = function["name"]
        mapping = tool_mapping.get(function_name)

        if mapping is None:
            continue

        server_name,tool_name = mapping
        if server_name == "rag_notebook" and tool_name in {
            "search_knowledge_base",
            "search_knowledge",
            "ask_knowledge_base",
        }:
            continue
        tool_parameters = function.get("parameters") or {}
        context_fields = frozenset(
            (tool_parameters.get("properties") or {}).keys()
        )
        args_schema = _build_args_model(
            f"MCPArgs_{server_name}_{tool_name}",
            tool_parameters,
        )

        async def invoke(
                _server_name: str = server_name,
                _tool_name: str = tool_name,
                _context_fields: frozenset[str] = context_fields,
                **kwargs: Any,
        ) -> str:
            # LangChain represents omitted optional fields as ``None``.
            # MCP schemas generally expect those fields to be absent so the
            # server-side default can apply; sending null causes validation
            # failures for tools such as GitHub search.
            arguments = {
                key: value
                for key, value in kwargs.items()
                if value is not None
            }

            if _server_name == "rag_notebook":
                if "user_id" in _context_fields:
                    arguments["user_id"] = user_id
                if "knowledge_base_id" in _context_fields:
                    arguments["knowledge_base_id"] = knowledge_base_id

            tool_result = await mcp_client_manager.call_tool(
                server_name=_server_name,
                tool_name=_tool_name,
                arguments=arguments,
                user_id=user_id,
                access_token=access_token,
            )

            return _json_text(tool_result)

        # MCP 工具的名称和参数模式在运行时发现，因此不能写成静态的
        # ``@tool`` 声明；调用同一个装饰器工厂生成动态工具实例。
        result.append(
            tool(
                f"mcp__{server_name}__{tool_name}",
                description=function.get(
                    "description",
                    f"MCP 工具 {server_name}.{tool_name}",
                ),
                args_schema=args_schema,
            )(invoke)
        )

    return result


async def build_all_agent_tools(
        *,
        db: AsyncSession,
        user_id: str,
        knowledge_base_id: str,
        access_token: str | None = None,
) -> list[BaseTool]:
    project_tools = build_project_tools(
        db=db,
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
    )

    mcp_tools = await build_mcp_tools(
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
        access_token=access_token,
    )

    return [
        *project_tools,
        *mcp_tools,
    ]

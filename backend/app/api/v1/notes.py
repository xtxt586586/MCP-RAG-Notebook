import json
from typing import Any, Literal
from uuid import UUID
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    Document,
    KnowledgeBase,
    Note,
    NoteTemplate,
    ReviewRecord,
)
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from app.schemas.note import NoteCreate, NoteResponse, NoteUpdate
from app.services.vector_store.milvus_indexing_service import (
    milvus_indexing_service,
)
from app.services.retrieval.hybrid_search_service import (
    hybrid_search_service,
)
from app.services.llm.deepseek_service import deepseek_service
from app.services.knowledge_base_service import (
    get_current_user_knowledge_base,
)
from app.services.knowledge_graph_service import knowledge_graph_service
from app.workers.tasks import extract_note_graph, index_note_vectors

router = APIRouter(
    prefix="/notes",
    tags=["笔记"],
)


class AutocompleteRequest(BaseModel):
    context: str


class WritingAssistRequest(BaseModel):
    content: str
    action: Literal["continue", "expand", "summarize", "polish"] = "continue"


class NoteTemplateRequest(BaseModel):
    name: str
    title: str = ""
    content: str = ""
    category: str = ""
    tags: str = ""


def serialize_note(note: Note) -> dict[str, Any]:
    return {
        "id": note.id,
        "user_id": note.user_id,
        "knowledge_base_id": note.knowledge_base_id,
        "source_document_id": note.source_document_id,
        "title": note.title,
        "content": note.content,
        "vector_index_status": note.vector_index_status,
        "vector_index_error": note.vector_index_error,
        "metadata": note.extra_metadata or {},
        "created_at": note.created_at,
        "updated_at": note.updated_at,
    }


def serialize_template(template: NoteTemplate) -> dict[str, Any]:
    return {
        "id": str(template.id),
        "name": template.name,
        "title": template.title,
        "content": template.content,
        "category": template.category,
        "tags": template.tags,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


@router.get("/templates")
async def list_note_templates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(NoteTemplate)
        .where(NoteTemplate.user_id == current_user.id)
        .order_by(NoteTemplate.created_at.desc())
    )
    return [serialize_template(template) for template in result.scalars().all()]


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_note_template(
    request: NoteTemplateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="模板名称不能为空")

    template = NoteTemplate(
        user_id=current_user.id,
        name=name[:120],
        title=request.title[:200],
        content=request.content,
        category=request.category[:80],
        tags=request.tags[:1000],
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return serialize_template(template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note_template(
    template_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(NoteTemplate).where(
            NoteTemplate.id == template_id,
            NoteTemplate.user_id == current_user.id,
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="模板不存在或不属于当前用户")

    await db.delete(template)
    await db.commit()


@router.put("/templates/{template_id}")
async def update_note_template(
    template_id: UUID,
    request: NoteTemplateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="模板名称不能为空")

    result = await db.execute(
        select(NoteTemplate).where(
            NoteTemplate.id == template_id,
            NoteTemplate.user_id == current_user.id,
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="模板不存在或不属于当前用户")

    template.name = name[:120]
    template.title = request.title[:200]
    template.content = request.content
    template.category = request.category[:80]
    template.tags = request.tags[:1000]
    await db.commit()
    await db.refresh(template)
    return serialize_template(template)


@router.post("/autocomplete")
async def autocomplete_note(
    request: AutocompleteRequest,
    current_user: CurrentUser,
) -> dict[str, str]:
    """Generate a short inline completion for the current user's editor."""
    context = request.context.strip()[-2000:]
    if not context:
        return {"completion": ""}

    try:
        completion = await deepseek_service.generate(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是笔记编辑器的内联补全助手。"
                        "只输出紧接当前光标位置的补全文本，"
                        "不要重复已有内容，不要解释，最多补全 80 个汉字。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"光标前内容：\n{context}\n\n请继续补全：",
                },
            ],
            temperature=0.2,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="AI 补全服务暂时不可用",
        ) from exc

    normalized = completion.strip()
    if normalized.startswith("```"):
        normalized = normalized.replace("```", "").strip()
    return {"completion": normalized[:500]}


@router.post("/assist/stream")
async def writing_assist_stream(
    request: WritingAssistRequest,
    current_user: CurrentUser,
) -> StreamingResponse:
    """Stream continue/expand/summarize/polish results for selected text."""
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="写作内容不能为空")

    action_labels = {
        "continue": "续写",
        "expand": "扩写",
        "summarize": "摘要",
        "polish": "润色",
    }
    action_label = action_labels[request.action]

    async def events():
        try:
            async for chunk in deepseek_service.stream_generate(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是中文笔记写作助手。"
                            "只输出处理后的正文，不要解释过程，不要添加标题。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"请对下面内容执行【{action_label}】操作：\n"
                            f"{content[:12000]}"
                        ),
                    },
                ],
                temperature=0.3,
            ):
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception:
            yield (
                "data: "
                f"{json.dumps({'error': 'AI 写作服务暂时不可用'}, ensure_ascii=False)}"
                "\n\n"
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def get_owned_knowledge_base(
    *,
    knowledge_base_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession,
) -> KnowledgeBase:
    return await get_current_user_knowledge_base(
        db=db,
        user_id=current_user.id,
        requested_id=knowledge_base_id,
    )


async def get_owned_note(
    *,
    note_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession,
) -> Note:
    result = await db.execute(
        select(Note).where(
            Note.id == note_id,
            Note.user_id == current_user.id,
        )
    )

    note = result.scalar_one_or_none()

    if note is None:
        raise HTTPException(
            status_code=404,
            detail="笔记不存在或不属于当前用户",
        )

    return note


@router.post(
    "",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_note(
    request: NoteCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    title = request.title.strip()

    if not title:
        raise HTTPException(
            status_code=422,
            detail="笔记标题不能为空",
        )

    knowledge_base = await get_owned_knowledge_base(
        knowledge_base_id=request.knowledge_base_id,
        current_user=current_user,
        db=db,
    )

    if request.source_document_id is not None:
        document_result = await db.execute(
            select(Document.id).where(
                Document.id == request.source_document_id,
                Document.knowledge_base_id == knowledge_base.id,
            )
        )

        if document_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=404,
                detail="来源文档不存在或不属于当前知识库",
            )

    note = Note(
        user_id=current_user.id,
        knowledge_base_id=knowledge_base.id,
        source_document_id=request.source_document_id,
        title=title,
        content=request.content,
        vector_index_status="pending",
        extra_metadata=request.metadata,
    )

    db.add(note)
    await db.flush()

    review_record = ReviewRecord(
        note_id=note.id,
        user_id=current_user.id,
        review_count=0,
        interval_days=1,
        next_review_at=(
                datetime.now(timezone.utc)
                + timedelta(days=1)
        ),
    )

    db.add(review_record)

    await db.commit()
    await db.refresh(note)

    try:
        index_note_vectors.delay(str(note.id), str(current_user.id))
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "笔记已保存，但向量索引任务提交失败 note_id=%s",
            note.id,
        )
        note.vector_index_status = "failed"
        note.vector_index_error = "索引任务提交失败，可重试。"
        await db.commit()
        await db.refresh(note)

    try:
        if settings.graph_auto_extract_enabled:
            extract_note_graph.delay(str(note.id), str(current_user.id))
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "笔记图谱任务提交失败 note_id=%s",
            note.id,
        )

    return serialize_note(note)


@router.get("")
async def search_notes(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    knowledge_base_id: UUID = Query(...),
    query: str | None = Query(
        default=None,
        max_length=2000,
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
) -> dict[str, Any]:
    await get_owned_knowledge_base(
        knowledge_base_id=knowledge_base_id,
        current_user=current_user,
        db=db,
    )

    statement = select(Note).where(
        Note.user_id == current_user.id,
        Note.knowledge_base_id == knowledge_base_id,
    )

    normalized_query = (query or "").strip()

    semantic_note_ids: list[UUID] = []
    if normalized_query:
        try:
            semantic_results = await hybrid_search_service.search(
                user_id=str(current_user.id),
                knowledge_base_id=str(knowledge_base_id),
                query=normalized_query,
                top_k=min(limit, 20),
                source="notes",
            )
            semantic_note_ids = [
                UUID(str(item["document_id"]))
                for item in semantic_results
                if item.get("document_id")
            ]
        except Exception:
            semantic_note_ids = []

        pattern = f"%{normalized_query}%"

        if semantic_note_ids:
            statement = statement.where(Note.id.in_(semantic_note_ids))
        else:
            statement = statement.where(
                or_(
                    Note.title.ilike(pattern),
                    Note.content.ilike(pattern),
                )
            )

    if semantic_note_ids:
        statement = statement.limit(limit)
    else:
        statement = statement.order_by(
            Note.updated_at.desc(),
            Note.created_at.desc(),
        ).limit(limit)

    result = await db.execute(statement)
    notes = result.scalars().all()

    if semantic_note_ids:
        note_by_id = {note.id: note for note in notes}
        notes = [
            note_by_id[note_id]
            for note_id in semantic_note_ids
            if note_id in note_by_id
        ][:limit]

    return {
        "items": [
            serialize_note(note)
            for note in notes
        ],
        "count": len(notes),
        "query": normalized_query,
        "knowledge_base_id": str(knowledge_base_id),
    }


@router.get(
    "/{note_id}",
    response_model=NoteResponse,
)
async def get_note(
    note_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    note = await get_owned_note(
        note_id=note_id,
        current_user=current_user,
        db=db,
    )

    return serialize_note(note)


@router.put(
    "/{note_id}",
    response_model=NoteResponse,
)
async def update_note(
    note_id: UUID,
    request: NoteUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    note = await get_owned_note(
        note_id=note_id,
        current_user=current_user,
        db=db,
    )

    if request.title is not None:
        title = request.title.strip()

        if not title:
            raise HTTPException(
                status_code=422,
                detail="笔记标题不能为空",
            )

        note.title = title

    content_changed = request.content is not None
    title_changed = request.title is not None

    if request.content is not None:
        note.content = request.content

    if request.metadata is not None:
        note.extra_metadata = request.metadata

    if request.source_document_id is not None:
        if note.knowledge_base_id is None:
            raise HTTPException(
                status_code=422,
                detail="当前笔记没有关联知识库",
            )

        document_result = await db.execute(
            select(Document.id).where(
                Document.id
                == request.source_document_id,
                Document.knowledge_base_id
                == note.knowledge_base_id,
            )
        )

        if (
            document_result.scalar_one_or_none()
            is None
        ):
            raise HTTPException(
                status_code=404,
                detail="来源文档不存在或不属于当前知识库",
            )

        note.source_document_id = (
            request.source_document_id
        )

    await db.commit()
    await db.refresh(note)

    if content_changed or title_changed:
        if note.knowledge_base_id is not None:
            note.vector_index_status = "pending"
            note.vector_index_error = None
            await db.commit()
            await db.refresh(note)
        try:
            if note.knowledge_base_id is not None:
                index_note_vectors.delay(str(note.id), str(current_user.id))
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "笔记已更新，但向量索引任务提交失败 note_id=%s",
                note.id,
            )
            note.vector_index_status = "failed"
            note.vector_index_error = "索引任务提交失败，可重试。"
            await db.commit()
            await db.refresh(note)

        try:
            if settings.graph_auto_extract_enabled:
                extract_note_graph.delay(str(note.id), str(current_user.id))
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "笔记图谱更新任务提交失败 note_id=%s",
                note.id,
            )

    return serialize_note(note)


@router.post(
    "/{note_id}/index",
    response_model=NoteResponse,
)
async def retry_note_index(
    note_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    note = await get_owned_note(
        note_id=note_id,
        current_user=current_user,
        db=db,
    )
    if note.knowledge_base_id is None:
        raise HTTPException(
            status_code=409,
            detail="笔记未关联知识库，无法建立检索索引",
        )

    note.vector_index_status = "pending"
    note.vector_index_error = None
    await db.commit()
    await db.refresh(note)

    try:
        index_note_vectors.delay(str(note.id), str(current_user.id))
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "笔记向量索引重试任务提交失败 note_id=%s",
            note.id,
        )
        note.vector_index_status = "failed"
        note.vector_index_error = "索引任务提交失败，可重试。"
        await db.commit()
        await db.refresh(note)

    return serialize_note(note)


@router.delete(
    "/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_note(
    note_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    note = await get_owned_note(
        note_id=note_id,
        current_user=current_user,
        db=db,
    )

    if note.knowledge_base_id is not None:
        await knowledge_graph_service.delete_source(
            db,
            user_id=current_user.id,
            knowledge_base_id=note.knowledge_base_id,
            source_type="note",
            source_id=note.id,
        )

    await db.delete(note)
    await db.commit()

    try:
        await milvus_indexing_service.delete_note_vectors(
            note_id=str(note_id),
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "笔记向量删除失败 note_id=%s",
            note_id,
        )

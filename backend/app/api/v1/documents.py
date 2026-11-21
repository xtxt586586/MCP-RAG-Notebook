# 文档管理路由模块
import json
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    Document,
    DocumentAsset,
    IngestionTask,
    KnowledgeBase,
)
from app.services.indexing.document_indexing_service import (
    document_indexing_service,
)
from app.services.llm.deepseek_service import (
    deepseek_service,
)
from app.services.parsing.parsing_service import (
    document_parsing_service,
)
from app.services.storage.minio_service import (
    minio_storage,
)
from app.services.vector_store.milvus_indexing_service import (
    milvus_indexing_service,
)
from app.services.knowledge_base_service import (
    get_current_user_knowledge_base,
)
from app.workers.tasks import ingest_document


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/documents",
    tags=["文档"],
)


ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp",
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".webm",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".m4v",
}

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp",
}

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".webm",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".m4v",
}

MAX_FILE_SIZE = 20 * 1024 * 1024

PROCESSING_STATUSES = {
    "PARSING",
    "EMBEDDING",
    "INDEXING",
}

FAILED_STATUS_BY_PROCESSING_STAGE = {
    "PARSING": "PARSE_FAILED",
    "EMBEDDING": "EMBEDDING_FAILED",
    "INDEXING": "INDEXING_FAILED",
}


class SummarizeDocumentRequest(BaseModel):
    max_length: int = Field(
        default=1000,
        ge=100,
        le=10000,
    )


async def get_owned_document(
    *,
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession,
) -> Document | None:
    result = await db.execute(
        select(Document)
        .join(
            KnowledgeBase,
            Document.knowledge_base_id
            == KnowledgeBase.id,
        )
        .where(
            Document.id == document_id,
            KnowledgeBase.user_id
            == current_user.id,
        )
    )

    return result.scalar_one_or_none()


def _is_stale_ingestion_task(task: IngestionTask) -> bool:
    if task.status != "RUNNING":
        return False

    last_update = task.updated_at or task.created_at
    if last_update is None:
        return True

    if last_update.tzinfo is None:
        last_update = last_update.replace(tzinfo=timezone.utc)

    return datetime.now(timezone.utc) - last_update > timedelta(
        seconds=max(60, settings.ingestion_stale_after_seconds),
    )


async def _reconcile_stale_ingestion(
    *,
    db: AsyncSession,
    document: Document,
    task: IngestionTask | None,
) -> bool:
    """Turn a dead worker attempt into a deletable failed document."""
    if (
        task is None
        or not _is_stale_ingestion_task(task)
        or document.status not in PROCESSING_STATUSES
    ):
        return False

    failed_status = FAILED_STATUS_BY_PROCESSING_STAGE[document.status]
    document.status = failed_status
    task.status = "FAILED"
    task.error_message = (
        "摄取任务长时间没有更新，已自动标记为失败；"
        "原始文件仍可删除或重新处理。"
    )
    await db.commit()
    await db.refresh(document)
    await db.refresh(task)
    logger.warning(
        "将过期文档摄取任务标记为失败：document_id=%s task_id=%s",
        document.id,
        task.id,
    )
    return True


async def _find_ready_content_duplicate(
    *,
    db: AsyncSession,
    knowledge_base_id: UUID,
    content_md5: str,
    file_size: int,
) -> Document | None:
    """Find an already indexed copy, including legacy rows without hashes.

    The original project deduplicates successful uploads by content MD5, not
    by display name.  Legacy rows created before ``content_md5`` existed are
    lazily backfilled only when their size makes a comparison worthwhile.
    """
    result = await db.execute(
        select(Document)
        .where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.status == "READY",
            Document.content_md5 == content_md5,
        )
        .order_by(Document.created_at.desc())
        .limit(1),
    )
    duplicate = result.scalar_one_or_none()
    if duplicate is not None:
        return duplicate

    legacy_result = await db.execute(
        select(Document)
        .where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.status == "READY",
            Document.content_md5.is_(None),
            Document.size_bytes == file_size,
        )
        .order_by(Document.created_at.desc()),
    )

    for candidate in legacy_result.scalars().all():
        try:
            existing_bytes = await minio_storage.download_bytes(
                candidate.object_name,
            )
        except Exception:
            logger.warning(
                "无法读取旧文档以计算内容哈希：document_id=%s",
                candidate.id,
                exc_info=True,
            )
            continue

        candidate_md5 = hashlib.md5(
            existing_bytes,
            usedforsecurity=False,
        ).hexdigest()
        candidate.content_md5 = candidate_md5

        if candidate_md5 == content_md5:
            await db.commit()
            return candidate

    await db.commit()
    return None


@router.get("")
async def list_documents(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    knowledge_base_id: UUID | None = Query(
        default=None,
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
) -> dict:
    statement = (
        select(Document)
        .join(
            KnowledgeBase,
            Document.knowledge_base_id
            == KnowledgeBase.id,
        )
        .where(
            KnowledgeBase.user_id
            == current_user.id,
        )
        .order_by(
            Document.created_at.desc()
        )
        .offset(offset)
        .limit(limit)
    )

    if knowledge_base_id is not None:
        statement = statement.where(
            Document.knowledge_base_id
            == knowledge_base_id
        )

    result = await db.execute(statement)
    documents = result.scalars().all()

    items = [
        {
            "id": str(document.id),
            "knowledge_base_id": str(
                document.knowledge_base_id
            ),
            "file_name": document.file_name,
            "mime_type": document.mime_type,
            "size_bytes": document.size_bytes,
            "status": document.status,
            "metadata": (
                document.extra_metadata or {}
            ),
            "created_at": document.created_at,
        }
        for document in documents
    ]

    return {
        "items": items,
        "count": len(items),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{document_id}/content")
async def get_document_content(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Return the uploaded file, or parsed text when available."""
    document = await get_owned_document(
        document_id=document_id,
        current_user=current_user,
        db=db,
    )

    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在或不属于当前用户")

    metadata = document.extra_metadata or {}
    object_name = metadata.get("parsed_text_object_name") or document.object_name
    content_type = document.mime_type or "application/octet-stream"

    try:
        content = await minio_storage.download_bytes(str(object_name))
    except Exception as exc:
        logger.exception("读取文档内容失败，document_id=%s", document.id)
        raise HTTPException(status_code=404, detail="文档内容暂不可用") from exc

    if object_name != document.object_name:
        content_type = "text/plain; charset=utf-8"

    encoded_file_name = quote(
        document.file_name,
        safe="",
    )

    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Content-Disposition": (
                "inline; "
                f"filename*=UTF-8''{encoded_file_name}"
            ),
        },
    )


@router.get("/{document_id}/chunks")
async def get_document_chunks(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the parsed chunks used to build the document index."""
    document = await get_owned_document(
        document_id=document_id,
        current_user=current_user,
        db=db,
    )

    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在或不属于当前用户")

    metadata = document.extra_metadata or {}
    chunks_object_name = metadata.get("chunks_object_name")

    if not chunks_object_name:
        return {
            "document_id": str(document.id),
            "file_name": document.file_name,
            "count": 0,
            "items": [],
        }

    try:
        chunks_bytes = await minio_storage.download_bytes(
            str(chunks_object_name),
        )
        chunks_payload = json.loads(
            chunks_bytes.decode("utf-8"),
        )
    except Exception as exc:
        logger.exception(
            "读取文档分块失败，document_id=%s",
            document.id,
        )
        raise HTTPException(status_code=404, detail="文档分块暂不可用") from exc

    if not isinstance(chunks_payload, list):
        raise HTTPException(status_code=422, detail="文档分块数据格式无效")

    items: list[dict[str, Any]] = []
    for chunk in chunks_payload:
        if not isinstance(chunk, dict):
            continue

        items.append(
            {
                "id": str(chunk.get("id", "")),
                "chunk_index": int(chunk.get("chunk_index", len(items))),
                "page_number": int(chunk.get("page_number", -1)),
                "content": str(chunk.get("content", "")),
                "source_type": str(chunk.get("source_type", "text")),
                "start_seconds": float(chunk.get("start_seconds", -1)),
                "end_seconds": float(chunk.get("end_seconds", -1)),
                "metadata": chunk.get("metadata") or {},
            }
        )

    return {
        "document_id": str(document.id),
        "file_name": document.file_name,
        "count": len(items),
        "items": items,
    }


@router.get("/{document_id}")
async def get_document_detail(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    document = await get_owned_document(
        document_id=document_id,
        current_user=current_user,
        db=db,
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="文档不存在或不属于当前用户",
        )

    task_result = await db.execute(
        select(IngestionTask)
        .where(
            IngestionTask.document_id
            == document.id
        )
        .order_by(
            IngestionTask.created_at.desc()
        )
        .limit(1)
    )

    task = task_result.scalar_one_or_none()

    await _reconcile_stale_ingestion(
        db=db,
        document=document,
        task=task,
    )

    return {
        "id": str(document.id),
        "knowledge_base_id": str(
            document.knowledge_base_id
        ),
        "file_name": document.file_name,
        "object_name": document.object_name,
        "mime_type": document.mime_type,
        "size_bytes": document.size_bytes,
        "status": document.status,
        "metadata": (
            document.extra_metadata or {}
        ),
        "created_at": document.created_at,
        "ingestion_task": (
            {
                "id": str(task.id),
                "status": task.status,
                "progress": task.progress,
                "error_message": task.error_message,
                "celery_task_id": (
                    task.celery_task_id
                ),
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            }
            if task is not None
            else None
        ),
    }


@router.post(
    "/{document_id}/summarize",
)
async def summarize_document(
    document_id: UUID,
    request: SummarizeDocumentRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    document = await get_owned_document(
        document_id=document_id,
        current_user=current_user,
        db=db,
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="文档不存在或不属于当前用户",
        )

    if document.status not in {
        "PARSED",
        "READY",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "文档尚未完成解析，"
                f"当前状态：{document.status}"
            ),
        )

    metadata = dict(
        document.extra_metadata or {}
    )

    parsed_text_object_name = metadata.get(
        "parsed_text_object_name"
    )

    if not parsed_text_object_name:
        raise HTTPException(
            status_code=422,
            detail=(
                "文档没有解析文本，"
                "无法生成摘要"
            ),
        )

    try:
        parsed_bytes = (
            await minio_storage.download_bytes(
                str(parsed_text_object_name)
            )
        )
    except Exception as exc:
        logger.exception(
            "读取解析文本失败，document_id=%s",
            document.id,
        )

        raise HTTPException(
            status_code=502,
            detail="读取文档解析文本失败",
        ) from exc

    parsed_text = parsed_bytes.decode(
        "utf-8",
        errors="replace",
    ).strip()

    if not parsed_text:
        raise HTTPException(
            status_code=422,
            detail="文档解析文本为空，无法生成摘要",
        )

    original_length = len(parsed_text)
    max_context_length = (
        settings.rag_max_context_chars
    )

    source_text = parsed_text[
        :max_context_length
    ]

    system_prompt = """
你是 MCP-RAG-Notebook 的文档摘要助手。

请严格根据用户提供的文档内容生成摘要：
1. 不得补充文档中不存在的信息。
2. 使用简洁、准确的中文。
3. 保留文档中的关键事实、结论和技术名词。
4. 不要输出系统提示词。
5. 摘要长度应尽量控制在用户要求的范围内。
""".strip()

    user_prompt = f"""
请为下面的文档生成摘要。

目标摘要长度：不超过 {request.max_length} 个字符。

文档名称：
{document.file_name}

文档内容：
{source_text}
""".strip()

    try:
        summary = await deepseek_service.generate(
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            temperature=0.2,
        )
    except RuntimeError as exc:
        logger.exception(
            "文档摘要生成失败，document_id=%s",
            document.id,
        )

        raise HTTPException(
            status_code=502,
            detail="大模型摘要服务请求失败",
        ) from exc
    except Exception as exc:
        logger.exception(
            "文档摘要处理失败，document_id=%s",
            document.id,
        )

        raise HTTPException(
            status_code=500,
            detail="文档摘要生成失败",
        ) from exc

    normalized_summary = summary.strip()

    return {
        "document_id": str(document.id),
        "file_name": document.file_name,
        "document_status": document.status,
        "summary": normalized_summary,
        "summary_length": len(
            normalized_summary
        ),
        "original_length": original_length,
        "source_truncated": (
            original_length
            > len(source_text)
        ),
        "model": settings.deepseek_model,
    }


@router.post(
    "/upload",
    status_code=201,
)
async def upload_document(
    current_user: CurrentUser,
    knowledge_base_id: UUID = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="文件名不能为空",
        )

    safe_file_name = Path(file.filename).name
    extension = Path(
        safe_file_name
    ).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                "当前支持 TXT、Markdown、PDF、DOCX、"
                "PPTX、XLSX、PNG、JPG、JPEG、BMP、"
                "WEBP、MP3、WAV、M4A、AAC、FLAC、"
                "OGG、WEBM、MP4、MOV、AVI、MKV 和 M4V"
            ),
        )

    # Read at most one byte beyond the limit so oversized uploads do not
    # allocate their entire contents in the application process.
    file_data = await file.read(MAX_FILE_SIZE + 1)

    if not file_data:
        raise HTTPException(
            status_code=400,
            detail="不能上传空文件",
        )

    if len(file_data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="文件不能超过 20MB",
        )

    knowledge_base = await get_current_user_knowledge_base(
        db=db,
        user_id=current_user.id,
        requested_id=knowledge_base_id,
    )
    knowledge_base_id = knowledge_base.id

    content_md5 = hashlib.md5(
        file_data,
        usedforsecurity=False,
    ).hexdigest()

    duplicate_document = await _find_ready_content_duplicate(
        db=db,
        knowledge_base_id=knowledge_base_id,
        content_md5=content_md5,
        file_size=len(file_data),
    )

    if duplicate_document is not None:
        logger.info(
            "跳过重复文档：user_id=%s file_name=%s existing_document_id=%s",
            current_user.id,
            safe_file_name,
            duplicate_document.id,
        )
        return {
            "id": str(duplicate_document.id),
            "knowledge_base_id": str(duplicate_document.knowledge_base_id),
            "file_name": duplicate_document.file_name,
            "object_name": duplicate_document.object_name,
            "mime_type": duplicate_document.mime_type,
            "size_bytes": duplicate_document.size_bytes,
            "status": duplicate_document.status,
            "content_md5": duplicate_document.content_md5,
            "duplicate": True,
            "message": "文件内容已存在，已跳过重复处理",
        }

    document_id = uuid4()

    object_name = (
        f"users/{current_user.id}/"
        f"knowledge-bases/{knowledge_base_id}/"
        f"documents/{document_id}/"
        f"{safe_file_name}"
    )

    document = Document(
        id=document_id,
        knowledge_base_id=knowledge_base_id,
        file_name=safe_file_name,
        object_name=object_name,
        mime_type=file.content_type,
        size_bytes=len(file_data),
        content_md5=content_md5,
        status="PENDING",
        extra_metadata={},
    )

    db.add(document)
    await db.commit()

    try:
        await minio_storage.upload_bytes(
            object_name=object_name,
            data=file_data,
            content_type=(
                file.content_type
                or "application/octet-stream"
            ),
        )
    except Exception as exc:
        logger.exception(
            "文件上传到 MinIO 失败，document_id=%s",
            document.id,
        )

        document.status = "UPLOAD_FAILED"
        await db.commit()

        raise HTTPException(
            status_code=500,
            detail="文件存储失败",
        ) from exc

    document.status = "UPLOADED"

    if extension in IMAGE_EXTENSIONS:
        db.add(
            DocumentAsset(
                document_id=document.id,
                asset_type="source_image",
                object_name=document.object_name,
                mime_type=(
                    file.content_type
                    or "application/octet-stream"
                ),
                size_bytes=len(file_data),
                extra_metadata={
                    "ocr_parser": "rapidocr",
                },
            )
        )

    if extension in AUDIO_EXTENSIONS:
        db.add(
            DocumentAsset(
                document_id=document.id,
                asset_type="source_audio",
                object_name=document.object_name,
                mime_type=(
                    file.content_type
                    or "application/octet-stream"
                ),
                size_bytes=len(file_data),
                extra_metadata={
                    "asr_parser": "faster-whisper",
                    "asr_model": "base",
                },
            )
        )

    if extension in VIDEO_EXTENSIONS:
        db.add(
            DocumentAsset(
                document_id=document.id,
                asset_type="source_video",
                object_name=document.object_name,
                mime_type=(
                    file.content_type
                    or "application/octet-stream"
                ),
                size_bytes=len(file_data),
                extra_metadata={
                    "asr_parser": (
                        "faster-whisper-video"
                    ),
                    "asr_model": "base",
                },
            )
        )

    task = IngestionTask(
        document_id=document.id,
        status="PENDING",
        progress=0,
    )

    db.add(task)
    await db.commit()
    await db.refresh(task)

    try:
        celery_result = ingest_document.delay(
            str(document.id),
            str(current_user.id),
        )
    except Exception as exc:
        logger.exception(
            "文档摄取任务投递失败，document_id=%s",
            document.id,
        )

        task.status = "FAILED"
        task.error_message = (
            "Celery 任务投递失败："
            f"{str(exc)[:1800]}"
        )

        await db.commit()

        raise HTTPException(
            status_code=503,
            detail=(
                "文件已上传，但异步处理任务"
                "投递失败，请稍后重试"
            ),
        ) from exc

    task.celery_task_id = celery_result.id
    await db.commit()

    return {
        "id": str(document.id),
        "knowledge_base_id": str(
            document.knowledge_base_id
        ),
        "file_name": document.file_name,
        "object_name": document.object_name,
        "mime_type": document.mime_type,
        "size_bytes": document.size_bytes,
        "content_md5": document.content_md5,
        "duplicate": False,
        "status": document.status,
        "ingestion_task_id": str(task.id),
        "celery_task_id": task.celery_task_id,
    }


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    document = await get_owned_document(
        document_id=document_id,
        current_user=current_user,
        db=db,
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="文档不存在或不属于当前用户",
        )

    task_result = await db.execute(
        select(IngestionTask)
        .where(IngestionTask.document_id == document.id)
        .order_by(IngestionTask.created_at.desc())
        .limit(1),
    )
    task = task_result.scalar_one_or_none()

    await _reconcile_stale_ingestion(
        db=db,
        document=document,
        task=task,
    )

    if document.status in PROCESSING_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                "文档正在处理中，暂时不能删除："
                f"{document.status}"
            ),
        )

    asset_result = await db.execute(
        select(DocumentAsset).where(
            DocumentAsset.document_id
            == document.id
        )
    )

    assets = asset_result.scalars().all()

    object_names: set[str] = {
        document.object_name
    }

    metadata = document.extra_metadata or {}

    for key in (
        "parsed_text_object_name",
        "chunks_object_name",
        "raw_text_object_name",
    ):
        object_name = metadata.get(key)

        if object_name:
            object_names.add(str(object_name))

    for asset in assets:
        object_names.add(asset.object_name)

    try:
        await milvus_indexing_service.delete_document_vectors(
            document_id=str(document.id)
        )

        for object_name in object_names:
            await minio_storage.delete_object(
                object_name
            )

    except Exception as exc:
        logger.exception(
            "清理文档外部资源失败，document_id=%s",
            document.id,
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "文档向量或文件清理失败，"
                "数据库记录未删除"
            ),
        ) from exc

    if task is not None and task.celery_task_id:
        try:
            ingest_document.AsyncResult(
                task.celery_task_id,
            ).revoke(terminate=False)
        except Exception:
            # The task is already stale; failure to revoke its result record
            # must not prevent deleting the user's document and assets.
            logger.warning(
                "撤销过期摄取任务失败：task_id=%s",
                task.celery_task_id,
                exc_info=True,
            )

    await db.delete(document)
    await db.commit()

    return {
        "document_id": str(document.id),
        "status": "DELETED",
        "message": (
            "文档、MinIO 文件和 Milvus 向量已删除"
        ),
    }


@router.post("/{document_id}/parse")
async def parse_uploaded_document(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    document = await get_owned_document(
        document_id=document_id,
        current_user=current_user,
        db=db,
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="文档不存在或不属于当前用户",
        )

    allowed_statuses = {
        "UPLOADED",
        "PARSE_FAILED",
        "PARSED",
    }

    if document.status not in allowed_statuses:
        raise HTTPException(
            status_code=409,
            detail=(
                "当前文档状态不允许解析："
                f"{document.status}"
            ),
        )

    try:
        return await document_parsing_service.parse(
            db,
            user_id=current_user.id,
            document=document,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "文档解析接口失败，document_id=%s",
            document.id,
        )

        raise HTTPException(
            status_code=500,
            detail="文档解析失败",
        ) from exc


@router.post("/{document_id}/index")
async def index_parsed_document(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    document = await get_owned_document(
        document_id=document_id,
        current_user=current_user,
        db=db,
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="文档不存在或不属于当前用户",
        )

    allowed_statuses = {
        "PARSED",
        "EMBEDDING_FAILED",
        "INDEXING_FAILED",
        "READY",
    }

    if document.status not in allowed_statuses:
        raise HTTPException(
            status_code=409,
            detail=(
                "当前文档状态不允许建立索引："
                f"{document.status}"
            ),
        )

    try:
        return await document_indexing_service.index_document(
            db,
            document=document,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "文档索引接口失败，document_id=%s",
            document.id,
        )

        raise HTTPException(
            status_code=500,
            detail="文档向量化或索引失败",
        ) from exc


@router.post("/{document_id}/retry")
async def retry_document_ingestion(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Requeue a failed ingestion task without uploading the file again."""
    document = await get_owned_document(
        document_id=document_id,
        current_user=current_user,
        db=db,
    )
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在或不属于当前用户")

    task_result = await db.execute(
        select(IngestionTask)
        .where(IngestionTask.document_id == document.id)
        .order_by(IngestionTask.created_at.desc())
        .limit(1),
    )
    task = task_result.scalar_one_or_none()
    task_status = task.status if task is not None else None

    retryable_document_statuses = {
        "UPLOADED",
        "PARSE_FAILED",
        "PARSED",
        "EMBEDDING_FAILED",
        "INDEXING_FAILED",
    }
    if document.status not in retryable_document_statuses and task_status != "FAILED":
        raise HTTPException(
            status_code=409,
            detail=f"当前文档状态不允许重试：{document.status}",
        )

    if task is None:
        task = IngestionTask(document_id=document.id, status="PENDING", progress=0)
        db.add(task)
    else:
        task.status = "PENDING"
        task.progress = 0
        task.error_message = None
        task.celery_task_id = None

    if document.status == "PARSE_FAILED" or task_status == "FAILED":
        document.status = "UPLOADED"
    elif document.status in {"EMBEDDING_FAILED", "INDEXING_FAILED"}:
        document.status = "PARSED"

    await db.commit()
    await db.refresh(task)

    try:
        celery_result = ingest_document.delay(
            str(document.id),
            str(current_user.id),
        )
    except Exception as exc:
        task.status = "FAILED"
        task.error_message = f"Celery 任务投递失败：{str(exc)[:1800]}"
        await db.commit()
        raise HTTPException(status_code=503, detail="重试任务投递失败，请稍后再试") from exc

    task.celery_task_id = celery_result.id
    await db.commit()
    return await get_document_detail(document.id, current_user, db)

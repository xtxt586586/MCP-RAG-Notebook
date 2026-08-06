import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Document, IngestionTask, KnowledgeBase
from app.services.storage.minio_service import minio_storage

from app.services.parsing.parsing_service import (
    document_parsing_service,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/documents",
    tags=["文档"],
)

ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
}

MAX_FILE_SIZE = 20 * 1024 * 1024


@router.post("/upload", status_code=201)
async def upload_document(
    user_id: UUID = Form(...),
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
    extension = Path(safe_file_name).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="当前只支持 TXT、Markdown 和 PDF",
        )

    file_data = await file.read()

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

    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.user_id == user_id,
        )
    )

    knowledge_base = result.scalar_one_or_none()

    if knowledge_base is None:
        raise HTTPException(
            status_code=404,
            detail="知识库不存在或不属于当前用户",
        )

    document_id = uuid4()

    object_name = (
        f"users/{user_id}/"
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

        document.status = "UPLOADED"

        task = IngestionTask(
            document_id=document.id,
            status="PENDING",
            progress=0,
        )

        db.add(task)
        await db.commit()

    except Exception:
        logger.exception("文件上传到 MinIO 失败")

        document.status = "UPLOAD_FAILED"
        await db.commit()

        raise HTTPException(
            status_code=500,
            detail="文件存储失败",
        )

    return {
        "id": str(document.id),
        "knowledge_base_id": str(document.knowledge_base_id),
        "file_name": document.file_name,
        "object_name": document.object_name,
        "mime_type": document.mime_type,
        "size_bytes": document.size_bytes,
        "status": document.status,
    }



@router.post("/{document_id}/parse")
async def parse_uploaded_document(
    document_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Document)
        .join(
            KnowledgeBase,
            Document.knowledge_base_id == KnowledgeBase.id,
        )
        .where(
            Document.id == document_id,
            KnowledgeBase.user_id == user_id,
        )
    )

    document = result.scalar_one_or_none()

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
                f"当前文档状态不允许解析："
                f"{document.status}"
            ),
        )

    try:
        return await document_parsing_service.parse(
            db,
            user_id=user_id,
            document=document,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="文档解析失败",
        ) from exc
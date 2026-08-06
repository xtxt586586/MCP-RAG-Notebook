import json
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models import Document, IngestionTask
from app.services.parsing.document_parser import parse_document
from app.services.parsing.text_chunker import create_chunks
from app.services.storage.minio_service import minio_storage


logger = logging.getLogger(__name__)


class DocumentParsingService:
    async def _get_or_create_task(
        self,
        db: AsyncSession,
        document_id: UUID,
    ) -> IngestionTask:
        result = await db.execute(
            select(IngestionTask)
            .where(
                IngestionTask.document_id == document_id
            )
            .order_by(
                IngestionTask.created_at.desc()
            )
            .limit(1)
        )

        task = result.scalar_one_or_none()

        if task is None:
            task = IngestionTask(
                document_id=document_id,
                status="PENDING",
                progress=0,
            )

            db.add(task)
            await db.flush()

        return task

    async def parse(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        document: Document,
    ) -> dict:
        task = await self._get_or_create_task(
            db,
            document.id,
        )

        document.status = "PARSING"
        task.status = "RUNNING"
        task.progress = 10
        task.error_message = None

        await db.commit()

        try:
            file_data = await minio_storage.download_bytes(
                document.object_name
            )

            task.progress = 20
            await db.commit()

            parsed_units, parser_name = await run_in_threadpool(
                parse_document,
                document.file_name,
                file_data,
            )

            source_type = (
                "pdf"
                if Path(document.file_name).suffix.lower() == ".pdf"
                else "text"
            )

            chunks = await run_in_threadpool(
                create_chunks,
                parsed_units,
                user_id=str(user_id),
                knowledge_base_id=str(
                    document.knowledge_base_id
                ),
                document_id=str(document.id),
                file_name=document.file_name,
                source_type=source_type,
            )

            task.progress = 30
            await db.commit()

            document_prefix = document.object_name.rsplit("/", 1)[0]

            parsed_text_object_name = (
                f"{document_prefix}/derived/parsed.txt"
            )

            chunks_object_name = (
                f"{document_prefix}/derived/chunks.json"
            )

            parsed_text = "\n\n".join(
                (
                    f"[Page {unit.page_number}]\n{unit.text}"
                    if unit.page_number >= 0
                    else unit.text
                )
                for unit in parsed_units
            )

            chunks_json = json.dumps(
                chunks,
                ensure_ascii=False,
                indent=2,
            )

            await minio_storage.upload_bytes(
                object_name=parsed_text_object_name,
                data=parsed_text.encode("utf-8"),
                content_type="text/plain; charset=utf-8",
            )

            await minio_storage.upload_bytes(
                object_name=chunks_object_name,
                data=chunks_json.encode("utf-8"),
                content_type="application/json",
            )

            current_metadata = dict(
                document.extra_metadata or {}
            )

            current_metadata.update(
                {
                    "parser": parser_name,
                    "chunk_count": len(chunks),
                    "parsed_text_object_name": (
                        parsed_text_object_name
                    ),
                    "chunks_object_name": (
                        chunks_object_name
                    ),
                }
            )

            document.extra_metadata = current_metadata
            document.status = "PARSED"

            task.status = "RUNNING"
            task.progress = 40
            task.error_message = None

            await db.commit()

            return {
                "document_id": str(document.id),
                "file_name": document.file_name,
                "status": document.status,
                "parser": parser_name,
                "chunk_count": len(chunks),
                "parsed_text_object_name": (
                    parsed_text_object_name
                ),
                "chunks_object_name": (
                    chunks_object_name
                ),
                "preview": [
                    {
                        "chunk_index": chunk["chunk_index"],
                        "page_number": chunk["page_number"],
                        "content": chunk["content"][:200],
                    }
                    for chunk in chunks[:3]
                ],
            }

        except Exception as exc:
            logger.exception(
                "文档解析失败，document_id=%s",
                document.id,
            )

            document.status = "PARSE_FAILED"
            task.status = "FAILED"
            task.error_message = str(exc)[:2000]

            await db.commit()

            raise


document_parsing_service = DocumentParsingService()
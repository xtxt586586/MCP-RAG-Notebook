import json
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import (
    run_in_threadpool,
)

from app.models import (
    Document,
    DocumentAsset,
    IngestionTask,
)
from app.services.parsing.document_parser import (
    parse_document,
)
from app.services.parsing.text_chunker import (
    create_chunks,
)
from app.services.storage.minio_service import (
    minio_storage,
)


logger = logging.getLogger(__name__)


class DocumentParsingService:
    async def _persist_parsed_assets(
        self,
        db: AsyncSession,
        *,
        document: Document,
        document_prefix: str,
        parsed_units: list,
    ) -> None:
        asset_sequence = 0

        for unit_index, unit in enumerate(
            parsed_units
        ):
            for asset_index, asset in enumerate(
                unit.assets
            ):
                data = asset.get("data")

                if not isinstance(
                    data,
                    (bytes, bytearray),
                ):
                    continue

                asset_type = str(
                    asset.get(
                        "asset_type",
                        "derived_asset",
                    )
                )[:32]

                mime_type = str(
                    asset.get(
                        "mime_type",
                        "application/octet-stream",
                    )
                )

                asset_metadata = dict(
                    asset.get("metadata") or {}
                )

                start_seconds = float(
                    asset_metadata.get(
                        "start_seconds",
                        0.0,
                    )
                )

                extension = (
                    ".jpg"
                    if mime_type == "image/jpeg"
                    else ".bin"
                )

                object_name = (
                    f"{document_prefix}/derived/"
                    f"assets/{asset_type}/"
                    f"{unit_index:04d}-"
                    f"{asset_index:02d}-"
                    f"{int(start_seconds * 1000):010d}"
                    f"{extension}"
                )

                await minio_storage.upload_bytes(
                    object_name=object_name,
                    data=bytes(data),
                    content_type=mime_type,
                )

                asset_metadata.update(
                    {
                        "object_name": object_name,
                        "source_unit_index": unit_index,
                        "asset_sequence": asset_sequence,
                    }
                )

                existing_asset_result = await db.execute(
                    select(DocumentAsset).where(
                        DocumentAsset.object_name
                        == object_name
                    )
                )

                existing_asset = (
                    existing_asset_result.scalar_one_or_none()
                )

                if existing_asset is None:
                    db.add(
                        DocumentAsset(
                            document_id=document.id,
                            asset_type=asset_type,
                            object_name=object_name,
                            mime_type=mime_type,
                            size_bytes=len(data),
                            extra_metadata=asset_metadata,
                        )
                    )

                unit.metadata.setdefault(
                    "asset_object_names",
                    [],
                ).append(object_name)

                asset.pop("data", None)
                asset["object_name"] = object_name
                asset_sequence += 1

    async def _get_or_create_task(
        self,
        db: AsyncSession,
        document_id: UUID,
    ) -> IngestionTask:
        result = await db.execute(
            select(IngestionTask)
            .where(
                IngestionTask.document_id
                == document_id
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
            file_data = (
                await minio_storage.download_bytes(
                    document.object_name
                )
            )

            task.progress = 20
            await db.commit()

            parsed_units, parser_name = (
                await run_in_threadpool(
                    parse_document,
                    document.file_name,
                    file_data,
                )
            )

            extension = Path(
                document.file_name
            ).suffix.lower()

            source_type = {
                ".pdf": "pdf",
                ".docx": "docx",
                ".pptx": "pptx",
                ".xlsx": "xlsx",
                ".png": "image",
                ".jpg": "image",
                ".jpeg": "image",
                ".bmp": "image",
                ".webp": "image",
                ".mp3": "audio",
                ".wav": "audio",
                ".m4a": "audio",
                ".aac": "audio",
                ".flac": "audio",
                ".ogg": "audio",
                ".webm": "audio",
                ".mp4": "video",
                ".mov": "video",
                ".avi": "video",
                ".mkv": "video",
                ".m4v": "video",
            }.get(
                extension,
                "text",
            )

            document_prefix = (
                document.object_name.rsplit(
                    "/",
                    1,
                )[0]
            )

            await self._persist_parsed_assets(
                db,
                document=document,
                document_prefix=document_prefix,
                parsed_units=parsed_units,
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

            parsed_text_object_name = (
                f"{document_prefix}/"
                "derived/parsed.txt"
            )

            chunks_object_name = (
                f"{document_prefix}/"
                "derived/chunks.json"
            )

            raw_text_object_name = (
                f"{document_prefix}/"
                "derived/raw.txt"
            )

            parsed_text = "\n\n".join(
                (
                    f"[Page {unit.page_number}]\n"
                    f"{unit.text}"
                    if unit.page_number >= 0
                    else unit.text
                )
                for unit in parsed_units
            )

            raw_units = [
                unit.raw_text
                for unit in parsed_units
                if unit.raw_text
            ]

            raw_text = "\n\n".join(
                raw_units
            )

            chunks_json = json.dumps(
                chunks,
                ensure_ascii=False,
                indent=2,
            )

            await minio_storage.upload_bytes(
                object_name=(
                    parsed_text_object_name
                ),
                data=parsed_text.encode(
                    "utf-8"
                ),
                content_type=(
                    "text/plain; charset=utf-8"
                ),
            )

            await minio_storage.upload_bytes(
                object_name=chunks_object_name,
                data=chunks_json.encode(
                    "utf-8"
                ),
                content_type=(
                    "application/json"
                ),
            )

            has_raw_text = bool(raw_text)

            if has_raw_text:
                await minio_storage.upload_bytes(
                    object_name=(
                        raw_text_object_name
                    ),
                    data=raw_text.encode(
                        "utf-8"
                    ),
                    content_type=(
                        "text/plain; charset=utf-8"
                    ),
                )

            multimodal_metadata: dict = {}

            for unit in parsed_units:
                if unit.metadata:
                    multimodal_metadata.update(
                        unit.metadata
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

            if has_raw_text:
                current_metadata.update(
                    {
                        "raw_text_object_name": (
                            raw_text_object_name
                        ),
                        "raw_text_preserved": True,
                    }
                )

            if multimodal_metadata:
                current_metadata[
                    "multimodal"
                ] = multimodal_metadata

            document.extra_metadata = (
                current_metadata
            )

            document.status = "PARSED"

            task.status = "RUNNING"
            task.progress = 40
            task.error_message = None

            await db.commit()

            return {
                "document_id": str(
                    document.id
                ),
                "file_name": document.file_name,
                "status": document.status,
                "parser": parser_name,
                "source_type": source_type,
                "chunk_count": len(chunks),
                "parsed_text_object_name": (
                    parsed_text_object_name
                ),
                "chunks_object_name": (
                    chunks_object_name
                ),
                "raw_text_object_name": (
                    raw_text_object_name
                    if has_raw_text
                    else None
                ),
                "multimodal_metadata": (
                    multimodal_metadata
                ),
                "preview": [
                    {
                        "chunk_index": chunk[
                            "chunk_index"
                        ],
                        "page_number": chunk[
                            "page_number"
                        ],
                        "content": chunk[
                            "content"
                        ][:200],
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


document_parsing_service = (
    DocumentParsingService()
)

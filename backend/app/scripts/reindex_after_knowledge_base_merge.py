"""Rebuild document and note vectors after a knowledge-base merge."""

import asyncio
import json

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models import Document, KnowledgeBase, Note
from app.services.indexing.document_indexing_service import (
    document_indexing_service,
)
from app.services.storage.minio_service import minio_storage
from app.services.vector_store.milvus_indexing_service import (
    milvus_indexing_service,
)


async def reindex_documents() -> tuple[int, int]:
    indexed = 0
    skipped = 0
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Document, KnowledgeBase.user_id)
                .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
                .order_by(Document.created_at.asc())
            )
            documents = result.all()

            for document, user_id in documents:
                chunks_object_name = (document.extra_metadata or {}).get(
                    "chunks_object_name"
                )
                if not chunks_object_name:
                    skipped += 1
                    print(f"skip document without chunks: {document.id}")
                    continue

                payload = json.loads(
                    (await minio_storage.download_bytes(chunks_object_name)).decode(
                        "utf-8"
                    )
                )
                for chunk in payload:
                    if isinstance(chunk, dict):
                        chunk["knowledge_base_id"] = str(
                            document.knowledge_base_id
                        )
                        chunk["user_id"] = str(user_id)

                await minio_storage.upload_bytes(
                    object_name=chunks_object_name,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    content_type="application/json",
                )
                await document_indexing_service.index_document(
                    db,
                    document=document,
                )
                indexed += 1
                print(f"indexed document {document.id}")

            note_result = await db.execute(
                select(Note)
                .where(Note.knowledge_base_id.is_not(None))
                .order_by(Note.created_at.asc())
            )
            notes = note_result.scalars().all()

        for note in notes:
            await milvus_indexing_service.replace_note_vectors(
                note_id=str(note.id),
                user_id=str(note.user_id),
                knowledge_base_id=str(note.knowledge_base_id),
                title=note.title,
                content=note.content,
                metadata=note.extra_metadata,
            )
            print(f"indexed note {note.id}")

    finally:
        await engine.dispose()

    return indexed, skipped


if __name__ == "__main__":
    documents, skipped = asyncio.run(reindex_documents())
    print(f"reindexed {documents} documents; skipped {skipped}")

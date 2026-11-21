"""Backfill semantic vectors for notes created before note indexing was enabled."""

import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models import Note
from app.services.vector_store.milvus_indexing_service import (
    milvus_indexing_service,
)


async def reindex_notes() -> int:
    indexed = 0
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Note)
                .where(Note.knowledge_base_id.is_not(None))
                .order_by(Note.created_at.asc())
            )
            notes = result.scalars().all()

        for note in notes:
            await milvus_indexing_service.replace_note_vectors(
                note_id=str(note.id),
                user_id=str(note.user_id),
                knowledge_base_id=str(note.knowledge_base_id),
                title=note.title,
                content=note.content,
                metadata=note.extra_metadata,
            )
            indexed += 1
            print(f"indexed note {note.id}")
    finally:
        await engine.dispose()

    return indexed


if __name__ == "__main__":
    print(f"indexed {asyncio.run(reindex_notes())} notes")

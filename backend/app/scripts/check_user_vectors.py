"""Print vector metadata counts for one user after a knowledge-base merge."""

from pymilvus import MilvusClient

from app.core.config import settings


USER_ID = "5c431a5b-b480-4c91-8741-f21aa7d2f7c7"


client = MilvusClient(uri=settings.milvus_uri)
try:
    rows = client.query(
        collection_name=settings.milvus_collection,
        filter=f'user_id == "{USER_ID}"',
        output_fields=["knowledge_base_id", "source_type", "document_id"],
        limit=10000,
    )
    print(
        {
            "rows": len(rows),
            "knowledge_base_ids": sorted(
                {row.get("knowledge_base_id") for row in rows}
            ),
            "documents": len({row.get("document_id") for row in rows}),
            "notes": sum(row.get("source_type") == "note" for row in rows),
        }
    )
finally:
    client.close()

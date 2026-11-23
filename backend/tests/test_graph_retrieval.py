from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.knowledge_graph_service import KnowledgeGraphService


@pytest.mark.asyncio
async def test_graph_context_resolves_document_sources_through_knowledge_base_owner():
    user_id = uuid4()
    knowledge_base_id = uuid4()
    document_id = uuid4()
    subject_id = uuid4()
    target_id = uuid4()
    relation = SimpleNamespace(
        source_type="document",
        source_id=document_id,
        source_entity_id=subject_id,
        target_entity_id=target_id,
        predicate="举办",
        evidence="青杉工作坊举办 Python 入门活动。",
    )
    subject = SimpleNamespace(id=subject_id, name="青杉工作坊", entity_type="机构")
    target = SimpleNamespace(id=target_id, name="Python 入门", entity_type="活动")
    relation_result = SimpleNamespace(all=lambda: [(relation, subject, target)])
    source_result = SimpleNamespace(scalar_one_or_none=lambda: "workshop.md")
    db = SimpleNamespace(execute=AsyncMock(side_effect=[relation_result, source_result]))

    result = await KnowledgeGraphService()._relation_context(
        db,
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
        entity_ids=[subject_id],
        entities=[subject],
        limit=8,
    )

    assert result["sources"] == [{
        "source_type": "document",
        "source_id": str(document_id),
        "title": "workshop.md",
        "citation": "[图谱1]",
    }]
    assert "[图谱1] 青杉工作坊 -[举办]-> Python 入门" in result["context"]
    source_query = str(db.execute.await_args_list[1].args[0])
    assert "knowledge_bases.user_id" in source_query
    assert "documents.user_id" not in source_query

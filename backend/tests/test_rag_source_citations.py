from unittest.mock import AsyncMock

import pytest

from app.services.rag import rag_service as rag_module
from app.services.rag.rag_service import RAGService


def test_sources_are_limited_to_citations_used_by_the_answer():
    sources = [
        {"citation": "[资料1]", "file_name": "library.md"},
        {"citation": "[资料2]", "file_name": "workshop.md"},
    ]

    filtered = RAGService.sources_cited_in_answer(
        "图书馆周一至周五开放至 20:00。[资料1]",
        sources,
    )

    assert filtered == [sources[0]]


def test_sources_are_preserved_when_answer_has_no_known_citation():
    sources = [
        {"citation": "[资料1]", "file_name": "library.md"},
        {"citation": "[资料2]", "file_name": "workshop.md"},
    ]

    assert RAGService.sources_cited_in_answer(
        "根据资料无法确定。",
        sources,
    ) == sources


def test_graph_sources_are_preserved_when_cited():
    sources = [
        {"citation": "[资料1]", "file_name": "library.md"},
        {"citation": "[图谱1]", "file_name": "Library entity"},
    ]

    assert RAGService.sources_cited_in_answer(
        "图书馆的开放时间与管理员关系见图谱。[图谱1]",
        sources,
    ) == [sources[1]]


def test_mixed_citations_keep_only_the_matching_document_and_graph_sources():
    sources = [
        {"citation": "[资料1]", "file_name": "library.md"},
        {"citation": "[资料2]", "file_name": "workshop.md"},
        {"citation": "[图谱1]", "file_name": "Library entity"},
    ]

    assert RAGService.sources_cited_in_answer(
        "开放时间见文档[资料1]，实体关系见图谱[图谱1]。",
        sources,
    ) == [sources[0], sources[2]]


def test_multi_digit_citation_does_not_match_a_lower_number():
    sources = [
        {"citation": "[资料1]", "file_name": "one.md"},
        {"citation": "[资料10]", "file_name": "ten.md"},
    ]

    assert RAGService.sources_cited_in_answer(
        "来源见[资料10]。",
        sources,
    ) == [sources[1]]


def test_each_pdf_chunk_has_its_own_citation_and_page():
    chunks = [
        {"document_id": "doc", "file_name": "test.pdf", "chunk_id": "doc:0", "chunk_index": 0, "page_number": 1, "content": "First page"},
        {"document_id": "doc", "file_name": "test.pdf", "chunk_id": "doc:1", "chunk_index": 1, "page_number": 2, "content": "Second page"},
    ]
    context, sources = RAGService._build_context(chunks)

    assert "[资料1]" in context and "[资料2]" in context
    assert [(source["citation"], source["page_number"], source["chunk_index"]) for source in sources] == [
        ("[资料1]", 1, 0), ("[资料2]", 2, 1),
    ]
    assert RAGService.sources_cited_in_answer("Second page [资料2]", sources) == [sources[1]]


def test_rag_prompt_explains_document_and_graph_citations():
    messages = RAGService._build_messages(
        query="图书馆的开放时间是什么？",
        context="文档证据 [资料1]\n图谱关系证据 [图谱1]",
    )

    assert "文档使用 [资料1]" in messages[0]["content"]
    assert "知识图谱关系使用 [图谱1]" in messages[0]["content"]
    assert "优先引用相关 [图谱N]" in messages[0]["content"]


@pytest.mark.asyncio
async def test_non_streaming_answer_returns_only_cited_sources(monkeypatch):
    source_one = {"citation": "[资料1]", "file_name": "library.md"}
    source_two = {"citation": "[资料2]", "file_name": "workshop.md"}
    service = RAGService()
    db = object()
    monkeypatch.setattr(
        service,
        "prepare_auto_context",
        AsyncMock(return_value={
            "query": "图书馆几点闭馆？",
            "retrieval_query": "图书馆几点闭馆？",
            "retrieval_mode": "hybrid",
            "route_score": 0.8,
            "context": "图书馆周一到周五 20:00 闭馆。[资料1]",
            "sources": [source_one, source_two],
        }),
    )
    monkeypatch.setattr(
        rag_module.deepseek_service,
        "generate",
        AsyncMock(return_value="周一至周五 20:00 闭馆。[资料1]"),
    )

    result = await service.answer(
        db=db,
        user_id="user-id",
        knowledge_base_id="knowledge-base-id",
        query="图书馆几点闭馆？",
    )

    assert result["sources"] == [source_one]
    assert service.prepare_auto_context.await_args.kwargs["db"] is db

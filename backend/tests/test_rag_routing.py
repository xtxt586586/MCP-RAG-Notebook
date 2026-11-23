import pytest
import asyncio
from uuid import uuid4

from app.core.config import settings
from app.services.rag.rag_service import RAGService
from app.services.rag import rag_service as rag_module


@pytest.fixture(autouse=True)
def isolate_query_embedding(monkeypatch):
    """Routing unit tests must not download a model or depend on network access."""
    async def fake_encode(texts):
        return [[1.0, 2.0] for _ in texts], [{7: 0.5} for _ in texts]

    monkeypatch.setattr(rag_module.bge_m3_embedding_service, "encode", fake_encode)


@pytest.mark.asyncio
async def test_auto_context_skips_hybrid_search_below_threshold(monkeypatch) -> None:
    service = RAGService()
    search_calls = []

    async def fake_route_score(**_kwargs):
        return settings.rag_min_relevance_score

    async def fake_search(**kwargs):
        search_calls.append(kwargs)
        return []

    monkeypatch.setattr(rag_module.hybrid_search_service, "route_score", fake_route_score)
    monkeypatch.setattr(rag_module.hybrid_search_service, "search", fake_search)

    result = await service.prepare_auto_context(
        user_id="user-1",
        knowledge_base_id="kb-1",
        query="普通问题",
    )

    assert result["retrieval_mode"] == "general"
    assert result["context"] == ""
    assert search_calls == []


@pytest.mark.asyncio
async def test_auto_context_uses_hybrid_results_after_route_passes(monkeypatch) -> None:
    service = RAGService()
    search_calls = []

    async def fake_route_score(**_kwargs):
        return settings.rag_min_relevance_score + 0.1

    async def fake_search(**kwargs):
        search_calls.append(kwargs)
        return [{
            "content": "资料内容",
            "document_id": "doc-1",
            "chunk_id": "chunk-1",
            "chunk_index": 0,
            "file_name": "资料.md",
            "page_number": 1,
            "score": 0.1,
        }]

    monkeypatch.setattr(rag_module.hybrid_search_service, "route_score", fake_route_score)
    monkeypatch.setattr(rag_module.hybrid_search_service, "search", fake_search)
    monkeypatch.setattr(settings, "rag_query_rewrite_enabled", False)

    result = await service.prepare_auto_context(
        user_id="user-1",
        knowledge_base_id="kb-1",
        query="资料问题",
    )

    assert result["retrieval_mode"] == "hybrid"
    assert "资料内容" in result["context"]
    assert result["route_score"] > settings.rag_min_relevance_score
    assert len(search_calls) == 1


@pytest.mark.asyncio
async def test_auto_context_reuses_original_query_vectors(monkeypatch) -> None:
    service = RAGService()
    encode_calls = []
    route_vectors = []
    search_vectors = []

    async def fake_encode(texts):
        encode_calls.append(texts)
        return [[1.0, 2.0]], [{7: 0.5}]

    async def fake_route_score(**kwargs):
        route_vectors.append(kwargs["dense_vector"])
        return settings.rag_min_relevance_score + 0.1

    async def fake_search(**kwargs):
        search_vectors.extend([
            kwargs["dense_vector"],
            kwargs["sparse_vector"],
        ])
        return [{
            "content": "资料内容",
            "document_id": "doc-1",
            "chunk_id": "chunk-1",
            "chunk_index": 0,
            "file_name": "资料.md",
            "page_number": 1,
            "score": 0.1,
        }]

    monkeypatch.setattr(rag_module.bge_m3_embedding_service, "encode", fake_encode)
    monkeypatch.setattr(rag_module.hybrid_search_service, "route_score", fake_route_score)
    monkeypatch.setattr(rag_module.hybrid_search_service, "search", fake_search)
    monkeypatch.setattr(settings, "rag_query_rewrite_enabled", False)

    result = await service.prepare_auto_context(
        user_id="user-1",
        knowledge_base_id="kb-1",
        query="资料问题",
    )

    assert result["retrieval_mode"] == "hybrid"
    assert encode_calls == [["资料问题"]]
    assert route_vectors == [[1.0, 2.0]]
    assert search_vectors == [[1.0, 2.0], {7: 0.5}]


@pytest.mark.asyncio
async def test_route_score_uses_milvus_cosine_similarity(monkeypatch) -> None:
    from app.services.retrieval import hybrid_search_service as retrieval_module
    from app.services.retrieval.hybrid_search_service import HybridSearchService

    async def fake_encode(_texts):
        return [[0.0] * 4], [{}]

    async def fake_run_in_threadpool(_func, **_kwargs):
        return [{"score": 0.8}]

    monkeypatch.setattr(
        retrieval_module.bge_m3_embedding_service,
        "encode",
        fake_encode,
    )
    monkeypatch.setattr(
        retrieval_module,
        "run_in_threadpool",
        fake_run_in_threadpool,
    )

    score = await HybridSearchService().route_score(
        user_id="user-1",
        knowledge_base_id="kb-1",
        query="test",
    )

    assert score == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_route_score_does_not_invert_weak_similarity(monkeypatch) -> None:
    from app.services.retrieval import hybrid_search_service as retrieval_module
    from app.services.retrieval.hybrid_search_service import HybridSearchService

    async def fake_run_in_threadpool(_func, **_kwargs):
        return [{"score": 0.1, "content": "unrelated document"}]

    monkeypatch.setattr(retrieval_module, "run_in_threadpool", fake_run_in_threadpool)
    score = await HybridSearchService().route_score(
        user_id="user-1", knowledge_base_id="kb-1", query="weather forecast",
        dense_vector=[1.0, 0.0],
    )
    assert score <= settings.rag_min_relevance_score


def test_lexical_route_fallback_recognizes_chinese_terms() -> None:
    from app.services.retrieval.hybrid_search_service import HybridSearchService

    score = HybridSearchService._lexical_relevance(
        "基于多因素规则算法提供定价建议的模型",
        "智能定价模型考虑出版年份、版次、品相、市场需求等多因素，提供参考建议。",
    )

    assert score >= 0.5
    assert HybridSearchService._lexical_relevance(
        "今天天气怎么样",
        "智能定价模型考虑出版年份、版次、品相、市场需求等多因素。",
    ) == 0.0


def test_graph_retrieval_ignores_generic_entity_matches() -> None:
    from types import SimpleNamespace

    from app.services.knowledge_graph_service import KnowledgeGraphService

    assert not KnowledgeGraphService._is_specific_entity_match(
        SimpleNamespace(normalized_name="模型")
    )
    assert KnowledgeGraphService._is_specific_entity_match(
        SimpleNamespace(normalized_name="定价算法")
    )


@pytest.mark.asyncio
async def test_route_score_requires_margin_without_lexical_evidence(monkeypatch) -> None:
    from app.services.retrieval import hybrid_search_service as retrieval_module
    from app.services.retrieval.hybrid_search_service import HybridSearchService

    async def fake_encode(_texts):
        return [[0.0] * 4], [{}]

    async def fake_run_in_threadpool(_func, **_kwargs):
        return [{"score": 0.49, "content": "完全无关的文档内容"}]

    monkeypatch.setattr(retrieval_module.bge_m3_embedding_service, "encode", fake_encode)
    monkeypatch.setattr(retrieval_module, "run_in_threadpool", fake_run_in_threadpool)

    score = await HybridSearchService().route_score(
        user_id="user-1",
        knowledge_base_id="kb-1",
        query="今天天气怎么样",
    )

    assert score == settings.rag_min_relevance_score


@pytest.mark.asyncio
async def test_search_falls_back_when_reranker_times_out(monkeypatch) -> None:
    from app.services.retrieval import hybrid_search_service as retrieval_module
    from app.services.retrieval.hybrid_search_service import HybridSearchService

    async def fake_encode(_texts):
        return [[0.0] * 4], [{}]

    async def fake_rerank(**_kwargs):
        await asyncio.sleep(0.05)
        return []

    async def fake_run_in_threadpool(_func, **_kwargs):
        return [{"score": 0.2, "content": "资料"}]

    monkeypatch.setattr(retrieval_module.bge_m3_embedding_service, "encode", fake_encode)
    monkeypatch.setattr(retrieval_module.bge_reranker_service, "rerank", fake_rerank)
    monkeypatch.setattr(retrieval_module, "run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(settings, "reranker_timeout_seconds", 0.001)

    results = await HybridSearchService().search(
        user_id="user-1",
        knowledge_base_id="kb-1",
        query="资料问题",
        top_k=1,
    )

    assert results[0]["score"] == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_graph_context_can_route_without_dense_threshold(monkeypatch) -> None:
    service = RAGService()
    user_id = uuid4()
    knowledge_base_id = uuid4()

    async def fake_graph_context(*_args, **_kwargs):
        return {
            "context": "[图谱1] A -[关联]-> B；来源：note.md",
            "sources": [{"source_type": "note", "title": "note.md"}],
            "entities": [],
        }

    async def fake_route_score(**_kwargs):
        return 0.1

    async def unexpected_search(**_kwargs):
        raise AssertionError("向量分数未过阈值时不应运行混合检索")

    monkeypatch.setattr(rag_module.knowledge_graph_service, "retrieve_context", fake_graph_context)
    monkeypatch.setattr(rag_module.hybrid_search_service, "route_score", fake_route_score)
    monkeypatch.setattr(rag_module.hybrid_search_service, "search", unexpected_search)

    result = await service.prepare_auto_context(
        db=object(),
        user_id=str(user_id),
        knowledge_base_id=str(knowledge_base_id),
        query="A 和 B 有什么关系？",
    )

    assert result["retrieval_mode"] == "graph"
    assert "A -[关联]-> B" in result["context"]
    assert result["sources"][0]["title"] == "note.md"

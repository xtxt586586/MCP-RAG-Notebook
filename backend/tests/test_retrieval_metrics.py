import hashlib

import pytest

from app.scripts.evaluate_retrieval import describe_ranked_chunks, score_chunks, score_documents, validate_chunk_fingerprint, validate_indexed_chunks


def test_document_metrics_deduplicate_chunks():
    results = [{"document_id": "a"}, {"document_id": "a"}, {"document_id": "b"}]
    recall, reciprocal_rank = score_documents(results, {"b", "c"}, 3)
    assert recall == pytest.approx(0.5)
    assert reciprocal_rank == pytest.approx(0.5)


def test_document_metrics_require_relevance_labels():
    with pytest.raises(ValueError):
        score_documents([], set(), 5)


def test_chunk_metrics_rank_exact_chunks_without_document_deduplication():
    results = [
        {"chunk_id": "doc-a:0", "document_id": "doc-a"},
        {"chunk_id": "doc-a:1", "document_id": "doc-a"},
        {"chunk_id": "doc-b:0", "document_id": "doc-b"},
    ]
    recall, reciprocal_rank = score_chunks(results, {"doc-a:1", "doc-b:0"}, 3)
    assert recall == pytest.approx(1.0)
    assert reciprocal_rank == pytest.approx(0.5)


def test_chunk_metrics_require_relevance_labels():
    with pytest.raises(ValueError, match="chunk"):
        score_chunks([], set(), 5)


def test_ranked_chunk_report_preserves_order_and_deduplicates():
    results = [
        {"chunk_id": "a:1", "document_id": "a", "chunk_index": 1},
        {"chunk_id": "a:1", "document_id": "a", "chunk_index": 1},
        {"chunk_id": "a:0", "document_id": "a", "chunk_index": 0},
        {"chunk_id": "b:0", "document_id": "b", "chunk_index": 0},
    ]
    assert describe_ranked_chunks(results, {"a": "guide.pdf"}, 2) == [
        "guide.pdf#1", "guide.pdf#0",
    ]


def test_chunk_fingerprint_detects_content_or_label_drift():
    chunks = [{"chunk_index": 0, "content": "原始内容"}]
    digest = hashlib.sha256("原始内容".encode("utf-8")).hexdigest()
    validate_chunk_fingerprint("guide.pdf#0", chunks, digest)
    with pytest.raises(ValueError, match="changed"):
        validate_chunk_fingerprint("guide.pdf#0", [{"chunk_index": 0, "content": "不同内容"}], digest)
    with pytest.raises(ValueError, match="SHA-256"):
        validate_chunk_fingerprint("guide.pdf#0", chunks, None)
    with pytest.raises(ValueError, match="exactly one"):
        validate_chunk_fingerprint("guide.pdf#0", chunks + chunks, digest)


def test_indexed_chunk_validation_checks_content_and_scope():
    digest = hashlib.sha256("内容".encode("utf-8")).hexdigest()
    expected = {"doc:0": ("guide.pdf#0", digest, "doc", 0)}
    row = {"id": "doc:0", "user_id": "user", "knowledge_base_id": "kb",
           "document_id": "doc", "chunk_index": 0, "source_type": "text", "content": "内容"}
    validate_indexed_chunks([row], expected, "user", "kb")
    with pytest.raises(ValueError, match="missing"):
        validate_indexed_chunks([], expected, "user", "kb")
    with pytest.raises(ValueError, match="scope"):
        validate_indexed_chunks([{**row, "user_id": "other"}], expected, "user", "kb")
    with pytest.raises(ValueError, match="changed"):
        validate_indexed_chunks([{**row, "content": "变化"}], expected, "user", "kb")

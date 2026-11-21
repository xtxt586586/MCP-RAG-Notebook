import pytest

from app.scripts.evaluate_retrieval import score_documents


def test_document_metrics_deduplicate_chunks():
    results = [{"document_id": "a"}, {"document_id": "a"}, {"document_id": "b"}]
    recall, reciprocal_rank = score_documents(results, {"b", "c"}, 3)
    assert recall == pytest.approx(0.5)
    assert reciprocal_rank == pytest.approx(0.5)


def test_document_metrics_require_relevance_labels():
    with pytest.raises(ValueError):
        score_documents([], set(), 5)

"""Evaluate retrieval against document-level relevance labels.

Run inside the backend container. The benchmark reads existing indexed documents;
it never creates or deletes a user, document, or collection.
"""
import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models import Document, KnowledgeBase
from app.services.embedding.bge_m3_service import bge_m3_embedding_service
from app.services.reranking.bge_reranker_service import bge_reranker_service
from app.services.retrieval.hybrid_search_service import hybrid_search_service


def score_documents(results, relevant, k):
    """Document Recall@K and reciprocal rank after deduplicating retrieved chunks."""
    ranked = list(dict.fromkeys(str(item["document_id"]) for item in results))[:k]
    relevant = set(relevant)
    if not relevant:
        raise ValueError("Retrieval relevance labels must contain at least one document")
    matches = len(set(ranked) & relevant)
    reciprocal_rank = next((1 / rank for rank, item in enumerate(ranked, 1) if item in relevant), 0.0)
    return matches / len(relevant), reciprocal_rank


async def run(args):
    labels_bytes = args.labels.read_bytes()
    data = json.loads(labels_bytes.decode("utf-8"))
    cases = data.get("cases", [])
    if not cases:
        raise ValueError("No labeled questions found")
    ids = [str(case.get("id", "")) for case in cases]
    if any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Each question must have a unique nonempty id")

    user_id, kb_id = UUID(args.user_id), UUID(args.knowledge_base_id)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Document).join(
            KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id,
        ).where(
            KnowledgeBase.user_id == user_id,
            Document.knowledge_base_id == kb_id,
            Document.status == "READY",
        ))).scalars().all()
    by_name = {}
    for document in rows:
        by_name.setdefault(document.file_name, []).append(str(document.id))
    for case in cases:
        names = case.get("relevant_documents", [])
        if not case.get("question", "").strip() or not names:
            raise ValueError(f"Question or relevance labels missing for {case['id']}")
        for name in names:
            if len(by_name.get(name, [])) != 1:
                raise ValueError(f"Expected exactly one READY document named {name!r}; found {len(by_name.get(name, []))}")

    # Load both models before timing; failures abort rather than silently
    # labeling an un-reranked run as reranked.
    await run_in_threadpool(bge_m3_embedding_service._get_model)
    await run_in_threadpool(bge_reranker_service._get_model)
    measurements = {name: [] for name in ("dense", "hybrid", "hybrid_rerank")}
    candidate_limit = min(max(args.k + 1, 6), 50)
    for case in cases:
        question = case["question"].strip()
        relevant = [by_name[name][0] for name in case["relevant_documents"]]
        start = perf_counter()
        dense, sparse = await bge_m3_embedding_service.encode([question])
        embedding_ms = (perf_counter() - start) * 1000
        results_by_mode = {}
        retrieval_ms = {}
        for mode in ("dense", "hybrid"):
            start = perf_counter()
            results_by_mode[mode] = await run_in_threadpool(
                hybrid_search_service._search_sync,
                user_id=str(user_id), knowledge_base_id=str(kb_id), source="documents",
                dense_vector=dense[0], sparse_vector=sparse[0], mode=mode,
                candidate_limit=candidate_limit,
            )
            retrieval_ms[mode] = (perf_counter() - start) * 1000
        start = perf_counter()
        reranked = await bge_reranker_service.rerank(query=question, results=results_by_mode["hybrid"])
        rerank_ms = (perf_counter() - start) * 1000
        variants = {
            "dense": (results_by_mode["dense"], embedding_ms + retrieval_ms["dense"]),
            "hybrid": (results_by_mode["hybrid"], embedding_ms + retrieval_ms["hybrid"]),
            "hybrid_rerank": (reranked, embedding_ms + retrieval_ms["hybrid"] + rerank_ms),
        }
        for name, (results, elapsed) in variants.items():
            recall, reciprocal_rank = score_documents(results[:args.k], relevant, args.k)
            measurements[name].append({"id": case["id"], "recall": recall, "reciprocal_rank": reciprocal_rank, "latency_ms": round(elapsed, 2)})
        print(f"evaluated {case['id']}", file=sys.stderr, flush=True)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_description": data.get("description", ""),
        "labels_sha256": hashlib.sha256(labels_bytes).hexdigest(),
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
        "ready_document_count": len(rows),
        "scope": "document-level; retrieved top-k chunks, deduplicated by document",
        "timing": "warm models; per-query embedding plus retrieval; rerank variant adds reranker time; sequential runs",
        "k": args.k,
        "candidate_limit": candidate_limit,
        "case_count": len(cases),
        "variants": {
            name: {"recall_at_k": mean(x["recall"] for x in values),
                   "mrr_at_k": mean(x["reciprocal_rank"] for x in values),
                   "latency_median_ms": median(x["latency_ms"] for x in values),
                   "cases": values}
            for name, values in measurements.items()
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--k", type=int, default=1, choices=range(1, 21))
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

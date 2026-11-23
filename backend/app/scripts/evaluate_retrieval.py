"""Evaluate retrieval against chunk-level relevance labels.

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

from pymilvus import MilvusClient
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models import Document, KnowledgeBase
from app.services.embedding.bge_m3_service import bge_m3_embedding_service
from app.services.reranking.bge_reranker_service import bge_reranker_service
from app.services.retrieval.hybrid_search_service import hybrid_search_service
from app.services.storage.minio_service import minio_storage


def score_documents(results, relevant, k):
    """Document Recall@K and reciprocal rank after deduplicating retrieved chunks."""
    ranked = list(dict.fromkeys(str(item["document_id"]) for item in results))[:k]
    relevant = set(relevant)
    if not relevant:
        raise ValueError("Retrieval relevance labels must contain at least one document")
    matches = len(set(ranked) & relevant)
    reciprocal_rank = next((1 / rank for rank, item in enumerate(ranked, 1) if item in relevant), 0.0)
    return matches / len(relevant), reciprocal_rank


def score_chunks(results, relevant, k):
    """Chunk Recall@K and reciprocal rank for explicitly labeled chunks."""
    ranked = list(dict.fromkeys(str(item["chunk_id"]) for item in results))[:k]
    relevant = set(relevant)
    if not relevant:
        raise ValueError("Retrieval relevance labels must contain at least one chunk")
    matches = len(set(ranked) & relevant)
    reciprocal_rank = next(
        (1 / rank for rank, item in enumerate(ranked, 1) if item in relevant),
        0.0,
    )
    return matches / len(relevant), reciprocal_rank


def describe_ranked_chunks(results, document_names, k):
    """Keep the ranked chunk identities needed to audit each metric."""
    ranked = []
    seen = set()
    for item in results:
        chunk_id = str(item["chunk_id"])
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        document_id = str(item["document_id"])
        name = document_names.get(document_id, document_id)
        ranked.append(f"{name}#{item['chunk_index']}")
        if len(ranked) == k:
            break
    return ranked


def validate_chunk_fingerprint(target, chunks, expected):
    """Reject stale labels even when the chunk index still exists."""
    if not isinstance(expected, str) or len(expected) != 64 or any(
        char not in "0123456789abcdef" for char in expected
    ):
        raise ValueError(f"Missing or invalid SHA-256 for labeled chunk {target!r}")
    try:
        index = int(target.rsplit("#", 1)[1])
        matches = [chunk for chunk in chunks if chunk.get("chunk_index") == index]
    except (AttributeError, IndexError, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid chunk data for {target!r}") from exc
    if len(matches) != 1 or not isinstance(matches[0].get("content"), str):
        raise ValueError(f"Expected exactly one parsed chunk for {target!r}")
    actual = hashlib.sha256(matches[0]["content"].encode("utf-8")).hexdigest()
    if actual != expected:
        raise ValueError(f"Chunk content changed for {target!r}; review the relevance labels")


def validate_indexed_chunks(rows, expected, user_id, knowledge_base_id):
    """Check the labeled Milvus records actually belong to the requested scope."""
    by_id = {str(row.get("id")): row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("Milvus returned duplicate chunk IDs")
    for chunk_id, (target, digest, document_id, index) in expected.items():
        row = by_id.get(chunk_id)
        if row is None:
            raise ValueError(f"Labeled chunk {target!r} is missing from the Milvus index")
        if (str(row.get("user_id")) != user_id
                or str(row.get("knowledge_base_id")) != knowledge_base_id
                or str(row.get("document_id")) != document_id
                or row.get("chunk_index") != index
                or row.get("source_type") == "note"):
            raise ValueError(f"Milvus scope or metadata mismatch for {target!r}")
        validate_chunk_fingerprint(target, [row], digest)


def verify_milvus_chunks(expected, user_id, knowledge_base_id):
    client = MilvusClient(uri=settings.milvus_uri)
    try:
        client.load_collection(collection_name=settings.milvus_collection)
        chunk_ids = list(expected)
        rows = []
        for start in range(0, len(chunk_ids), 100):
            rows.extend(client.get(
                collection_name=settings.milvus_collection,
                ids=chunk_ids[start:start + 100],
                output_fields=["id", "user_id", "knowledge_base_id", "document_id",
                               "chunk_index", "source_type", "content"],
                consistency_level="Strong",
            ))
        validate_indexed_chunks(rows, expected, user_id, knowledge_base_id)
    finally:
        client.close()


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
        by_name.setdefault(document.file_name, []).append(document)
    document_names = {str(document.id): document.file_name for document in rows}
    fingerprints = data.get("chunk_sha256")
    if not isinstance(fingerprints, dict):
        raise ValueError("Labels must contain chunk_sha256 fingerprints")
    checked_chunks = {}
    expected_indexed = {}
    for case in cases:
        targets = case.get("relevant_chunks", [])
        if (
            not case.get("question", "").strip()
            or not case.get("answerable")
            or not case.get("expected_answer", "").strip()
            or not targets
        ):
            raise ValueError(f"Question or relevance labels missing for {case['id']}")
        resolved = []
        for target in targets:
            try:
                name, index_text = target.rsplit("#", 1)
                chunk_index = int(index_text)
            except (AttributeError, ValueError) as exc:
                raise ValueError(f"Invalid relevant chunk {target!r} in {case['id']}") from exc
            if len(by_name.get(name, [])) != 1:
                raise ValueError(f"Expected exactly one READY document named {name!r}; found {len(by_name.get(name, []))}")
            document = by_name[name][0]
            chunk_count = int((document.extra_metadata or {}).get("chunk_count", 0))
            if chunk_index < 0 or chunk_index >= chunk_count:
                raise ValueError(
                    f"Chunk {target!r} is outside the indexed chunk range 0..{chunk_count - 1}"
                )
            if name not in checked_chunks:
                object_name = (document.extra_metadata or {}).get("chunks_object_name")
                if not object_name:
                    raise ValueError(f"Parsed chunks are unavailable for {name!r}")
                payload = json.loads((await minio_storage.download_bytes(str(object_name))).decode("utf-8"))
                if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
                    raise ValueError(f"Invalid parsed chunks for {name!r}")
                checked_chunks[name] = payload
            validate_chunk_fingerprint(target, checked_chunks[name], fingerprints.get(target))
            chunk_id = f"{document.id}:{chunk_index}"
            expected_indexed[chunk_id] = (target, fingerprints[target], str(document.id), chunk_index)
            resolved.append(chunk_id)
        case["_resolved_relevant_chunks"] = resolved

    await run_in_threadpool(verify_milvus_chunks, expected_indexed, str(user_id), str(kb_id))

    # Load both models before timing; failures abort rather than silently
    # labeling an un-reranked run as reranked.
    await run_in_threadpool(bge_m3_embedding_service._get_model)
    await run_in_threadpool(bge_reranker_service._get_model)
    measurements = {name: [] for name in ("dense", "hybrid", "hybrid_rerank")}
    candidate_limit = min(max(args.k + 1, 6), 50)
    for case in cases:
        question = case["question"].strip()
        relevant = case["_resolved_relevant_chunks"]
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
            recall, reciprocal_rank = score_chunks(results, relevant, args.k)
            measurements[name].append({
                "id": case["id"],
                "relevant_chunks": case["relevant_chunks"],
                "ranked_chunks": describe_ranked_chunks(results, document_names, args.k),
                "recall": recall,
                "reciprocal_rank": reciprocal_rank,
                "latency_ms": round(elapsed, 2),
            })
        print(f"evaluated {case['id']}", file=sys.stderr, flush=True)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_description": data.get("description", ""),
        "labels_sha256": hashlib.sha256(labels_bytes).hexdigest(),
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
        "ready_document_count": len(rows),
        "ready_chunk_count": sum(
            int((document.extra_metadata or {}).get("chunk_count", 0))
            for document in rows
        ),
        "scope": "chunk-level; exact indexed chunk IDs (document UUID and chunk index)",
        "label_validation": "SHA-256 of labeled chunk contents and ownership checked against stored chunk objects and Milvus records; vector values are not independently verified",
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

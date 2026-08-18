"""混合检索：向量(pgvector 余弦) + 关键词(BM25) → RRF 融合，按可读 KB 过滤。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.embedding import embed_query
from app.config import settings
from app.db.models import Chunk, Document
from app.services import bm25 as bm25_svc


@dataclass
class SourceChunk:
    chunk_id: int
    kb_id: int
    document_id: int
    chunk_index: int
    content: str
    score: float
    doc_name: str
    source_url: Optional[str]
    source_type: str


def _vector_search(db: Session, kb_ids: list[int], query_vec: list[float], limit: int):
    sim = 1 - Chunk.embedding.cosine_distance(query_vec)
    stmt = (
        select(
            Chunk.id,
            Chunk.kb_id,
            Chunk.document_id,
            Chunk.chunk_index,
            Chunk.content,
            sim.label("score"),
        )
        .where(Chunk.kb_id.in_(kb_ids))
        .order_by(sim.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    return {r.id: r for r in rows}, [r.id for r in rows]


def _rrf(rank_lists: list[list[int]], weights: list[float], k: int) -> list[int]:
    scores: dict[int, float] = {}
    for rl, w in zip(rank_lists, weights):
        for rank, cid in enumerate(rl):
            scores[cid] = scores.get(cid, 0.0) + w / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


def retrieve(
    db: Session,
    kb_ids: list[int],
    query: str,
    top_k: Optional[int] = None,
    mode: Optional[str] = None,
    threshold: Optional[float] = None,
) -> list[SourceChunk]:
    top_k = top_k or settings.rag_top_k
    mode = mode or settings.rag_retrieve_mode
    threshold = threshold if threshold is not None else settings.rag_score_threshold
    if not kb_ids:
        return []

    query_vec = embed_query(query)
    candidate = max(top_k * 3, 40)

    vector_map, vector_order = _vector_search(db, kb_ids, query_vec, candidate)
    bm25_pairs = bm25_svc.bm25_search(db, kb_ids, query, top_k=candidate)
    bm25_order = [cid for cid, _ in bm25_pairs]
    bm25_scores = {cid: float(score) for cid, score in bm25_pairs}

    if mode == "vector":
        ordered_ids = vector_order
    elif mode == "keyword":
        ordered_ids = bm25_order
    else:  # mix
        w = settings.bm25_weight
        ordered_ids = _rrf(
            [vector_order, bm25_order], [1 - w, w], settings.rrf_k
        )

    # 硬门限：向量相似度低于阈值的片段不进入候选（避免误引）
    if mode != "keyword":
        ordered_ids = [cid for cid in ordered_ids if vector_map.get(cid) and vector_map[cid].score >= threshold]

    ordered_ids = ordered_ids[:top_k]
    if not ordered_ids:
        return []

    # 补齐 vector_map 未覆盖的 chunk（keyword 模式下的纯 BM25 命中），
    # 否则这些块会因缺元数据被静默丢弃
    missing = [cid for cid in ordered_ids if cid not in vector_map]
    if missing:
        extra_rows = (
            db.execute(select(Chunk).where(Chunk.id.in_(missing))).scalars().all()
        )
        for c in extra_rows:
            vector_map[c.id] = c

    # 取文档元信息
    doc_ids = {vector_map[c].document_id for c in ordered_ids if c in vector_map}
    doc_rows = db.execute(
        select(Document.id, Document.title, Document.source_url, Document.source_type)
        .where(Document.id.in_(doc_ids))
    ).all() if doc_ids else []
    doc_meta = {d.id: d for d in doc_rows}

    results: list[SourceChunk] = []
    for cid in ordered_ids:
        r = vector_map.get(cid)
        if r is None:
            continue
        dm = doc_meta.get(r.document_id)
        # 分数：向量相似度优先，纯 BM25 命中用 BM25 分
        vec_score = getattr(r, "score", None)
        score = float(vec_score) if vec_score is not None else bm25_scores.get(cid, 0.0)
        results.append(
            SourceChunk(
                chunk_id=r.id,
                kb_id=r.kb_id,
                document_id=r.document_id,
                chunk_index=r.chunk_index,
                content=r.content,
                score=round(score, 4),
                doc_name=dm.title if dm else f"doc-{r.document_id}",
                source_url=dm.source_url if dm else None,
                source_type=dm.source_type if dm else "file",
            )
        )
    return results

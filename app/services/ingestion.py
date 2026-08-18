"""采集编排：解析 → 分块 → 嵌入 → 落库 → 重建 BM25。"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.clients.embedding import embed_texts
from app.config import settings
from app.db.models import Chunk, Document, KB
from app.services import audit as audit_svc
from app.services.chunking import chunk_text
from app.services.parser import parsers


def _choose_strategy(filename: str, source_type: str) -> str:
    low = filename.lower()
    if source_type == "url":
        return "fixed_token"
    if low.endswith((".docx", ".md", ".markdown")):
        return "heading_level"
    return "fixed_token"


def _store(db: Session, kb_id: int, doc: Document, chunks: list[str],
           vectors: list[list[float]], user_id: int | None) -> int:
    for i, (text, vec) in enumerate(zip(chunks, vectors)):
        db.add(
            Chunk(
                kb_id=kb_id,
                document_id=doc.id,
                chunk_index=i,
                content=text,
                embedding=vec,
                metadata_json=json.dumps({"index": i}, ensure_ascii=False),
            )
        )
    doc.chunk_count = len(chunks)
    doc.status = "done"


def ingest_file(db: Session, kb_id: int, data: bytes, filename: str,
                user_id: int | None = None) -> dict:
    kb = db.get(KB, kb_id)
    if not kb:
        raise ValueError("知识库不存在")
    doc = Document(kb_id=kb_id, title=filename, source_type="file", status="pending")
    db.add(doc)
    db.flush()

    try:
        title, text = parsers.dispatch("file", data=data, filename=filename)
        strategy = _choose_strategy(filename, "file")
        chunks = chunk_text(
            text, strategy, settings.chunk_size, settings.chunk_overlap
        )
        if not chunks:
            raise ValueError("未能从文档中提取到有效文本")
        vectors, tok = embed_texts(chunks)
        _store(db, kb_id, doc, chunks, vectors, user_id)
        db.commit()
        from app.services import bm25 as bm25_svc

        bm25_svc.rebuild_kb_index(db, kb_id)
        if tok:
            audit_svc.log_token_usage(db, "embedding", input_tokens=tok, user_id=user_id)
        return {"document_id": doc.id, "title": title, "chunk_count": len(chunks)}
    except Exception as e:
        doc.status = "failed"
        db.commit()
        raise RuntimeError(f"文档入库失败：{e}") from e


def ingest_url(db: Session, kb_id: int, url: str, title: str | None = None,
               user_id: int | None = None) -> dict:
    kb = db.get(KB, kb_id)
    if not kb:
        raise ValueError("知识库不存在")
    doc = Document(kb_id=kb_id, title=title or url, source_type="url",
                   source_url=url, status="pending")
    db.add(doc)
    db.flush()
    try:
        t, text = parsers.dispatch("url", url=url)
        title = title or t or url
        doc.title = title
        chunks = chunk_text(text, "fixed_token", settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            raise ValueError("未能从网页中提取到有效文本")
        vectors, tok = embed_texts(chunks)
        _store(db, kb_id, doc, chunks, vectors, user_id)
        db.commit()
        from app.services import bm25 as bm25_svc

        bm25_svc.rebuild_kb_index(db, kb_id)
        if tok:
            audit_svc.log_token_usage(db, "embedding", input_tokens=tok, user_id=user_id)
        return {"document_id": doc.id, "title": title, "chunk_count": len(chunks)}
    except Exception as e:
        doc.status = "failed"
        db.commit()
        raise RuntimeError(f"网页入库失败：{e}") from e

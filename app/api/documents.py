"""文档接入 API：上传文件、添加网页、列表、删除、分块预览。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.response import ok
from app.config import settings
from app.db.models import Chunk, Document, KB
from app.db.session import get_session
from app.security.jwt import get_current_admin
from app.security.rbac import can_upload_kb

router = APIRouter()


class UrlIn(BaseModel):
    url: str
    title: str | None = None


def _assert_upload(db: Session, admin, kb_id: int):
    kb = db.get(KB, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not can_upload_kb(db, admin, kb_id):
        raise HTTPException(status_code=403, detail="无该知识库上传权限")


@router.post("/kbs/{kb_id}/documents/upload")
def upload_document(
    kb_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    admin=Depends(get_current_admin),
):
    _assert_upload(db, admin, kb_id)
    from app.services.ingestion import ingest_file

    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过大小限制（{settings.max_upload_mb}MB）",
        )
    result = ingest_file(db, kb_id, data, file.filename or "upload.bin")
    return ok(result)


@router.post("/kbs/{kb_id}/documents/url")
def add_url_document(
    kb_id: int,
    body: UrlIn,
    db: Session = Depends(get_session),
    admin=Depends(get_current_admin),
):
    _assert_upload(db, admin, kb_id)
    from app.services.ingestion import ingest_url

    result = ingest_url(db, kb_id, body.url, body.title)
    return ok(result)


@router.get("/kbs/{kb_id}/documents")
def list_documents(
    kb_id: int,
    db: Session = Depends(get_session),
    admin=Depends(get_current_admin),
):
    if not db.get(KB, kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    docs = db.query(Document).filter_by(kb_id=kb_id).order_by(Document.id.desc()).all()
    return ok(
        [
            {
                "id": d.id,
                "title": d.title,
                "source_type": d.source_type,
                "source_url": d.source_url,
                "status": d.status,
                "chunk_count": d.chunk_count,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]
    )


@router.delete("/documents/{doc_id}")
def delete_document(
    doc_id: int,
    db: Session = Depends(get_session),
    admin=Depends(get_current_admin),
):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not can_upload_kb(db, admin, doc.kb_id):
        raise HTTPException(status_code=403, detail="无删除权限")
    db.delete(doc)
    db.commit()
    # 重建该 KB 的 BM25 索引
    from app.services.bm25 import rebuild_kb_index

    rebuild_kb_index(db, doc.kb_id)
    return ok(msg="已删除并重建索引")


@router.get("/documents/{doc_id}/chunks")
def preview_chunks(
    doc_id: int,
    limit: int = 20,
    db: Session = Depends(get_session),
    admin=Depends(get_current_admin),
):
    chunks = (
        db.query(Chunk)
        .filter_by(document_id=doc_id)
        .order_by(Chunk.chunk_index)
        .limit(limit)
        .all()
    )
    return ok(
        [{"chunk_index": c.chunk_index, "content": c.content[:500]} for c in chunks]
    )

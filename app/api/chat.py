"""Web 端问答 API（SSE 流式），供管理后台联调与测试。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_session
from app.security.jwt import get_current_admin
from app.security.rbac import can_read_kb, user_readable_kb_ids
from app.services.rag import stream_answer

router = APIRouter()


class ChatIn(BaseModel):
    question: str
    kb_id: int | None = None
    history: list[dict] | None = None


def _resolve_kb_ids(db: Session, user: User, kb_id: int | None) -> list[int]:
    readable = user_readable_kb_ids(db, user)
    if kb_id is not None:
        if kb_id not in readable:
            raise HTTPException(status_code=403, detail="无该知识库读取权限")
        return [kb_id]
    return readable


@router.post("/chat")
def chat(body: ChatIn, user: User = Depends(get_current_admin), db: Session = Depends(get_session)):
    kb_ids = _resolve_kb_ids(db, user, body.kb_id)

    def event_gen():
        for ev in stream_answer(db, user, body.question, kb_ids, body.history):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

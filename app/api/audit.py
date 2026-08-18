"""审计日志与 Token 用量查看（仅超级管理员）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.response import ok
from app.db.models import AuditLog, TokenUsage, User
from app.db.session import get_session
from app.security.jwt import get_current_admin
from app.security.rbac import is_super_admin

router = APIRouter()


@router.get("/audit/logs")
def list_logs(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    if not is_super_admin(admin):
        raise HTTPException(status_code=403, detail="仅超级管理员可查看审计")
    rows = (
        db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    )
    return ok(
        [
            {
                "id": r.id,
                "user_id": r.user_id,
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "detail": r.detail,
                "ip": r.ip,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    )


@router.get("/audit/usage")
def usage_summary(
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    if not is_super_admin(admin):
        raise HTTPException(status_code=403, detail="仅超级管理员可查看用量")
    total = db.query(func.coalesce(func.sum(TokenUsage.estimated_cost), 0)).scalar()
    chat_tokens = (
        db.query(
            func.coalesce(func.sum(TokenUsage.input_tokens), 0),
            func.coalesce(func.sum(TokenUsage.output_tokens), 0),
        )
        .filter(TokenUsage.type == "chat")
        .first()
    )
    embed_tokens = (
        db.query(func.coalesce(func.sum(TokenUsage.input_tokens), 0))
        .filter(TokenUsage.type == "embedding")
        .scalar()
    )
    return ok(
        {
            "total_cost": round(float(total), 4),
            "chat_input_tokens": int(chat_tokens[0]),
            "chat_output_tokens": int(chat_tokens[1]),
            "embedding_tokens": int(embed_tokens),
        }
    )

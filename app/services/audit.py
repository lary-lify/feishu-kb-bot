"""审计日志与 Token 用量记录。"""
from __future__ import annotations

from app.config import settings
from app.db.models import AuditLog, TokenUsage
from app.db.session import Session


def log_audit(
    db: Session,
    user_id: int | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            detail=detail,
            ip=ip,
        )
    )
    db.commit()


def log_token_usage(
    db: Session,
    type_: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    user_id: int | None = None,
    conversation_id: int | None = None,
    message_id: int | None = None,
) -> None:
    if type_ == "embedding":
        cost = input_tokens / 1000 * settings.price_embedding_per_1k
    else:
        cost = (
            input_tokens / 1000 * settings.price_input_per_1k
            + output_tokens / 1000 * settings.price_output_per_1k
        )
    db.add(
        TokenUsage(
            type=type_,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=round(cost, 6),
        )
    )
    db.commit()

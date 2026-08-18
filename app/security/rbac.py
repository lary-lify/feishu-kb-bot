"""RBAC 辅助：知识库可读/可写判定、用户可读 KB 集合。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import KBPermission, KB, Role, User


def user_readable_kb_ids(db: Session, user: User) -> list[int]:
    """返回该用户可读的所有知识库 id（shared 库全员可读 + private 库按授权）。"""
    readable: set[int] = set()
    for kb in db.query(KB).all():
        if kb.mode == "shared":
            readable.add(kb.id)
        elif kb.owner_id == user.id:
            readable.add(kb.id)
    # 显式授权（含 private 库）
    perms = db.query(KBPermission).filter_by(user_id=user.id).all()
    for p in perms:
        if p.perm in ("read", "upload", "admin"):
            readable.add(p.kb_id)
    return sorted(readable)


def can_read_kb(db: Session, user: User, kb_id: int) -> bool:
    return kb_id in user_readable_kb_ids(db, user)


def can_upload_kb(db: Session, user: User, kb_id: int) -> bool:
    """可上传：super_admin、KB 拥有者、或被授予 upload/admin 的用户。"""
    if user.role.name == "super_admin":
        return True
    kb = db.get(KB, kb_id)
    if kb and kb.owner_id == user.id:
        return True
    perm = (
        db.query(KBPermission)
        .filter_by(user_id=user.id, kb_id=kb_id)
        .first()
    )
    return perm is not None and perm.perm in ("upload", "admin")


def is_super_admin(user: User) -> bool:
    return user.role.name == "super_admin"

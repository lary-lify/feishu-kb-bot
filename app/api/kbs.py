"""知识库与权限管理 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.response import ok
from app.db.models import KB, KBPermission, Role, User
from app.db.session import get_session
from app.security.jwt import get_current_admin
from app.security.rbac import can_read_kb, can_upload_kb, is_super_admin

router = APIRouter()


class KBCreate(BaseModel):
    name: str
    description: str | None = None
    mode: str = "shared"  # private | shared


class PermIn(BaseModel):
    user_id: int
    perm: str = "read"  # read | upload | admin


def _kb_out(kb: KB, db: Session, user: User) -> dict:
    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
        "mode": kb.mode,
        "owner_id": kb.owner_id,
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
        "can_read": can_read_kb(db, user, kb.id),
        "can_upload": can_upload_kb(db, user, kb.id),
    }


@router.post("/kbs")
def create_kb(
    body: KBCreate,
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    if not (is_super_admin(admin) or admin.role.name == "dept_admin"):
        raise HTTPException(status_code=403, detail="仅超级管理员/部门管理员可建库")
    if db.query(KB).filter_by(name=body.name).first():
        raise HTTPException(status_code=409, detail="同名知识库已存在")
    if body.mode not in ("private", "shared"):
        raise HTTPException(status_code=400, detail="mode 必须为 private 或 shared")
    kb = KB(name=body.name, description=body.description, mode=body.mode, owner_id=admin.id)
    db.add(kb)
    db.flush()
    # 创建者自动获得 admin 授权
    db.add(KBPermission(kb_id=kb.id, user_id=admin.id, perm="admin"))
    db.commit()
    db.refresh(kb)
    return ok(_kb_out(kb, db, admin))


@router.get("/kbs")
def list_kbs(db: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    kbs = db.query(KB).order_by(KB.id).all()
    return ok([_kb_out(kb, db, admin) for kb in kbs])


@router.get("/kbs/{kb_id}")
def get_kb(kb_id: int, db: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    kb = db.get(KB, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return ok(_kb_out(kb, db, admin))


@router.delete("/kbs/{kb_id}")
def delete_kb(kb_id: int, db: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    kb = db.get(KB, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not is_super_admin(admin) and not (
        kb.owner_id == admin.id
    ):
        raise HTTPException(status_code=403, detail="仅超级管理员或库拥有者可删除")
    db.delete(kb)  # 级联删除文档与分块
    db.commit()
    return ok(msg="已删除")


@router.get("/kbs/{kb_id}/permissions")
def list_perms(kb_id: int, db: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    perms = db.query(KBPermission).filter_by(kb_id=kb_id).all()
    out = []
    for p in perms:
        u = db.get(User, p.user_id)
        out.append({"user_id": p.user_id, "username": u.username if u else "?", "perm": p.perm})
    return ok(out)


@router.post("/kbs/{kb_id}/permissions")
def grant_perm(
    kb_id: int,
    body: PermIn,
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    kb = db.get(KB, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not is_super_admin(admin) and kb.owner_id != admin.id:
        raise HTTPException(status_code=403, detail="仅超级管理员或库拥有者可授权")
    if body.perm not in ("read", "upload", "admin"):
        raise HTTPException(status_code=400, detail="perm 必须为 read/upload/admin")
    existing = db.query(KBPermission).filter_by(kb_id=kb_id, user_id=body.user_id).first()
    if existing:
        existing.perm = body.perm
    else:
        db.add(KBPermission(kb_id=kb_id, user_id=body.user_id, perm=body.perm))
    db.commit()
    return ok(msg="授权成功")

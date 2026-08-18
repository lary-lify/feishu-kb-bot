"""用户与角色管理 API（仅超级管理员）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.response import ok
from app.db.models import Role, User
from app.db.session import get_session
from app.security.jwt import get_current_admin, hash_password
from app.security.rbac import is_super_admin

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"  # super_admin | dept_admin | user
    dept: str | None = None


@router.get("/users")
def list_users(db: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    if not is_super_admin(admin):
        raise HTTPException(status_code=403, detail="仅超级管理员可管理用户")
    users = db.query(User).order_by(User.id).all()
    return ok(
        [
            {
                "id": u.id,
                "username": u.username,
                "role": u.role.name,
                "dept": u.dept,
                "open_id": u.open_id,
            }
            for u in users
        ]
    )


@router.post("/users")
def create_user(
    body: UserCreate,
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    if not is_super_admin(admin):
        raise HTTPException(status_code=403, detail="仅超级管理员可创建用户")
    if db.query(User).filter_by(username=body.username).first():
        raise HTTPException(status_code=409, detail="用户名已存在")
    role = db.query(Role).filter_by(name=body.role).first()
    if not role:
        raise HTTPException(status_code=400, detail="角色不存在")
    u = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        role_id=role.id,
        dept=body.dept,
    )
    db.add(u)
    db.commit()
    return ok({"id": u.id, "username": u.username})


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    if not is_super_admin(admin):
        raise HTTPException(status_code=403, detail="仅超级管理员可删除用户")
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.username == "admin":
        raise HTTPException(status_code=400, detail="默认管理员不可删除")
    db.delete(u)
    db.commit()
    return ok(msg="已删除")

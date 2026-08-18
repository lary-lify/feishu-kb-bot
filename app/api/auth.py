"""管理员认证：登录、当前用户。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.response import ok
from app.db.models import User
from app.db.session import get_session
from app.security.jwt import (
    create_access_token,
    get_current_admin,
    verify_password,
)

router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_session)):
    user = db.query(User).filter_by(username=body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token(user.id, user.role.name)
    return ok({"access_token": token, "role": user.role.name, "username": user.username})


@router.get("/auth/me")
def me(user: User = Depends(get_current_admin)):
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "role": user.role.name,
            "dept": user.dept,
            "open_id": user.open_id,
        }
    )

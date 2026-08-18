"""数据库初始化：建表、建向量索引、初始化角色与超级管理员。

用法：
    python -m app.db.init_db
（在应用启动 startup 中也会自动调用 init_db()）
"""
from __future__ import annotations

from sqlalchemy import text

from app.config import settings
from app.db.models import Base, Role, User
from app.db.session import SessionLocal, engine
from app.security.jwt import hash_password
from sqlalchemy.orm import Session


def init_db() -> None:
    # 1. 启用 vector 扩展
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # 2. 建表
    Base.metadata.create_all(bind=engine)

    # 3. HNSW 余弦索引（加速向量检索）
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chunks_embedding "
                "ON chunks USING hnsw (embedding vector_cosine_ops)"
            )
        )

    # 4. 种子数据：角色 + 默认管理员
    with SessionLocal() as db:
        _seed_roles(db)
        _seed_admin(db)
        db.commit()


def _seed_roles(db: Session) -> None:
    existing = {r.name for r in db.query(Role).all()}
    for name, desc in [
        ("super_admin", "超级管理员"),
        ("dept_admin", "部门管理员"),
        ("user", "普通用户"),
    ]:
        if name not in existing:
            db.add(Role(name=name, description=desc))


def _seed_admin(db: Session) -> None:
    admin_role = db.query(Role).filter_by(name="super_admin").first()
    if db.query(User).filter_by(username=settings.default_admin_username).first():
        return
    db.add(
        User(
            username=settings.default_admin_username,
            hashed_password=hash_password(settings.default_admin_password),
            role_id=admin_role.id,
            dept="IT",
        )
    )


if __name__ == "__main__":
    init_db()
    print("数据库初始化完成。")

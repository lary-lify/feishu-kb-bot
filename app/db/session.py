"""同步数据库引擎与会话（psycopg + pgvector）。

所有 FastAPI 路由使用同步 `def`，由 Starlette 在线程池中执行，
因此事件循环不会被阻塞；pgvector 类型通过 connect 事件注册。
"""
from __future__ import annotations

from collections.abc import Iterator

from pgvector.psycopg import register_vector
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)

# 在每次新建连接时注册 pgvector 类型，使 psycopg 能正确收发 vector
@event.listens_for(engine, "connect")
def _register_vector(dbapi_conn, _record):
    register_vector(dbapi_conn)


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI 依赖：提供同步会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

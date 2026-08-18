"""ORM 模型：用户/角色/知识库/文档/分块/审计/用量/会话。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------- 角色 ----------------
class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)  # super_admin|dept_admin|user
    description: Mapped[str | None] = mapped_column(String(128))

    users: Mapped[list["User"]] = relationship(back_populates="role")


# ---------------- 用户 ----------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    open_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), default=3)
    dept: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    role: Mapped["Role"] = relationship(back_populates="users")


# ---------------- 知识库 ----------------
class KB(Base):
    __tablename__ = "kbs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="shared")  # private|shared
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # 删除知识库时由 DB 级联清理其文档/权限（passive_deletes 让 ORM 信任 DB 级联）
    documents: Mapped[list["Document"]] = relationship(
        back_populates="kb", passive_deletes=True
    )
    permissions: Mapped[list["KBPermission"]] = relationship(
        back_populates="kb", passive_deletes=True
    )


# ---------------- 知识库权限 ----------------
class KBPermission(Base):
    __tablename__ = "kb_permissions"
    __table_args__ = (
        UniqueConstraint("kb_id", "user_id", name="uq_kb_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("kbs.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    perm: Mapped[str] = mapped_column(String(16), default="read")  # read|upload|admin

    kb: Mapped["KB"] = relationship(back_populates="permissions")


# ---------------- 文档 ----------------
class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("kbs.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(16))  # file|url
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|done|failed
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    kb: Mapped["KB"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


# ---------------- 分块（含向量） ----------------
class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("kbs.id", ondelete="CASCADE"))
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="chunks")


# HNSW 向量索引（在 init_db 中以 raw SQL 创建，确保参数正确）
Index("ix_chunks_kb_id", Chunk.kb_id)


# ---------------- 审计日志 ----------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ---------------- Token 用量 ----------------
class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(16))  # chat|embedding
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ---------------- 会话 / 消息（Web 端多轮用） ----------------
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(16))  # user|assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

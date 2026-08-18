"""应用配置：从 .env 读取（pydantic-settings）。"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 应用
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    # CORS 允许的来源（逗号分隔）。留空 = 仅同源访问（推荐）；填了才开启跨域
    cors_origins: str = ""

    # 数据库
    database_url: str = "postgresql+psycopg://kb_user:kb_password@db:5432/kb_db"

    # JWT
    jwt_secret: str = "change_me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    default_admin_username: str = "admin"
    default_admin_password: str = "Admin@123456"

    # 飞书
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_bot_name: str = ""

    # 通义 Embedding
    dashscope_api_key: str = ""
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # RAG
    rag_top_k: int = 5
    rag_score_threshold: float = 0.30
    rag_retrieve_mode: str = "mix"  # vector | keyword | mix
    rag_query_rewrite: bool = False  # 是否先做 LLM 查询改写再检索（多一次调用）
    rrf_k: int = 60
    bm25_weight: float = 0.30
    chunk_size: int = 512
    chunk_overlap: int = 128
    max_upload_mb: int = 20  # 上传文档大小上限（MB）

    # 价格（元/千 token）— 仅用于用量估算
    price_embedding_per_1k: float = 0.0007
    price_input_per_1k: float = 0.001
    price_output_per_1k: float = 0.002


settings = Settings()

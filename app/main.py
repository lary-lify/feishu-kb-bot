"""FastAPI 入口：中间件、路由挂载、静态管理 UI、启动飞书长连接。"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import audit, auth, chat, documents, kbs, users
from app.common.response import (
    business_error_handler,
    err,
    http_error_handler,
    unhandled_handler,
)
from app.config import settings
from app.db.init_db import init_db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("kb-bot")

app = FastAPI(title="飞书内部客服助手", version="1.0.0")

# CORS：默认仅同源（管理 UI 与 API 同域部署，无需跨域）；
# 如需跨域前端，在 .env 配置 CORS_ORIGINS=https://a.com,https://b.com
_cors_origins = (
    [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if settings.cors_origins
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # 通配 * 与凭据互斥；显式配置了来源才允许携带凭据
    allow_credentials=("*" not in _cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求 ID 日志中间件
@app.middleware("http")
async def request_log(request: Request, call_next):
    rid = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    logger.info("→ %s %s [%s]", request.method, request.url.path, rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


# 异常处理器
app.add_exception_handler(Exception, unhandled_handler)
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

app.add_exception_handler(StarletteHTTPException, http_error_handler)
from app.common.response import BusinessError  # noqa: E402

app.add_exception_handler(BusinessError, business_error_handler)


# 路由
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(kbs.router, prefix="/api", tags=["kbs"])
app.include_router(users.router, prefix="/api", tags=["users"])
app.include_router(documents.router, prefix="/api", tags=["documents"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(audit.router, prefix="/api", tags=["audit"])


@app.on_event("startup")
def on_startup() -> None:
    _check_security_config()
    logger.info("初始化数据库 ...")
    _init_db_with_retry()
    logger.info("数据库就绪。")
    _maybe_start_feishu()


def _init_db_with_retry(retries: int = 10, delay: float = 3.0) -> None:
    """Postgres 容器可能晚于应用就绪，重试建表/初始化，避免启动即崩。"""
    last_exc: Exception | None = None
    for i in range(retries):
        try:
            init_db()
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.error(
                "数据库初始化失败（第 %d/%d 次）：%s；%s 秒后重试...",
                i + 1, retries, exc, delay,
            )
            if i < retries - 1:
                time.sleep(delay)
    raise RuntimeError(f"数据库初始化失败（已重试 {retries} 次）：{last_exc}")


def _check_security_config() -> None:
    """启动安全自检：JWT 密钥为默认值/占位符/过短时拒绝启动（防 token 伪造）。"""
    secret = settings.jwt_secret
    weak = (
        not secret
        or secret.lower() == "change_me"
        or "change_me" in secret.lower()
        or len(secret) < 16
    )
    if not weak:
        return
    if os.getenv("ALLOW_DEFAULT_SECRET") == "1":
        logger.warning("JWT_SECRET 使用弱默认值，仅限开发环境使用！生产环境必须配置强密钥。")
        return
    raise RuntimeError(
        "JWT_SECRET 未配置强密钥（默认/占位/过短），存在严重安全风险（token 可被伪造）。"
        "请在 .env 中配置至少 16 位的随机密钥；仅限本地开发可设 ALLOW_DEFAULT_SECRET=1 临时绕过。"
    )


def _maybe_start_feishu() -> None:
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        logger.warning("未配置飞书 APP_ID/APP_SECRET，飞书机器人未启动（仅 Web/API 可用）。")
        return
    try:
        from app.feishu_bot.bot import start_feishu_bot

        t = threading.Thread(target=start_feishu_bot, daemon=True)
        t.start()
        logger.info("飞书长连接线程已启动。")
    except Exception as exc:  # noqa: BLE001
        logger.exception("飞书机器人启动失败：%s", exc)


@app.get("/api/health")
def health():
    return {"status": "ok", "feishu": bool(settings.feishu_app_id)}


# 静态管理 UI
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app", host=settings.app_host, port=settings.app_port, reload=False
    )

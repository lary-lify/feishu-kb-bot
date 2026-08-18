"""飞书长连接机器人：接收 @消息 → 私有知识库检索 → 回复含引用来源的卡片。"""
from __future__ import annotations

import json
import logging
import re
import threading

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from app.clients.feishu import send_card
from app.config import settings
from app.db.models import KB, Role, User
from app.db.session import SessionLocal
from app.feishu_bot.card import build_card
from app.security.rbac import can_read_kb, user_readable_kb_ids
from app.services import audit as audit_svc
from app.services.rag import generate_answer

logger = logging.getLogger("kb-bot.feishu")

_MENTION_RE = re.compile(r"<at[^>]*>.*?</at>", re.DOTALL)
_AT_NAME_RE = re.compile(r"@[\w一-鿿\- ]{1,30}")


def _strip_mention(text: str) -> str:
    text = _MENTION_RE.sub("", text)
    text = _AT_NAME_RE.sub("", text)
    return text.strip()


def _resolve_user(db, open_id: str) -> User:
    u = db.query(User).filter_by(open_id=open_id).first()
    if u:
        return u
    role = db.query(Role).filter_by(name="user").first()
    u = User(username=f"feishu_{open_id[-12:]}", open_id=open_id, role_id=role.id if role else 3)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _resolve_scope(db, user: User, question: str):
    """支持 `/kb <知识库名> 问题` 限定范围；否则检索全部可读库。"""
    m = re.match(r"^/kb\s+(\S+)\s+(.*)", question, re.DOTALL)
    if m:
        name, q = m.group(1), m.group(2).strip()
        kb = db.query(KB).filter_by(name=name).first()
        if not kb:
            return None, f"未找到知识库「{name}」"
        if not can_read_kb(db, user, kb.id):
            return None, f"您无知识库「{name}」的读取权限"
        return [kb.id], q
    return user_readable_kb_ids(db, user), question


def _handle_message(data: P2ImMessageReceiveV1) -> None:
    event = getattr(data, "event", None)
    if not event:
        return
    msg = getattr(event, "message", None)
    if not msg:
        return

    chat_type = getattr(msg, "chat_type", "group") or "group"
    msg_type = getattr(msg, "message_type", "")
    if msg_type != "text":
        # 仅处理文本；其余类型忽略（可按需扩展）
        return

    mentions = getattr(msg, "mentions", None) or []
    # 群聊：仅当被 @ 时响应（飞书默认仅推送 @ 消息；此处再次确认有提及）
    if chat_type == "group" and not mentions:
        return

    content = getattr(msg, "content", "") or "{}"
    try:
        text = json.loads(content).get("text", "")
    except Exception:
        text = ""

    question = _strip_mention(text)
    if not question:
        _reply(msg, "请在 @ 我 之后输入您的问题，例如：@客服助手 退货流程是什么？")
        return

    chat_id = getattr(msg, "chat_id", "")
    sender_open_id = ""
    sender = getattr(msg, "sender", None)
    if sender and getattr(sender, "sender_id", None):
        sender_open_id = getattr(sender.sender_id, "open_id", "") or ""

    with SessionLocal() as db:
        user = _resolve_user(db, sender_open_id) if sender_open_id else _anon_user(db)
        kb_ids, q = _resolve_scope(db, user, question)
        if kb_ids is None:
            _reply(msg, q)
            return
        if not kb_ids:
            _reply(msg, "您当前没有可读取的知识库，请联系管理员授权。")
            return
        try:
            answer, sources = generate_answer(db, user, q, kb_ids)
        except Exception as e:  # noqa: BLE001
            logger.exception("RAG 生成失败")
            _reply(msg, f"检索或生成时发生错误：{e}")
            return
        audit_svc.log_audit(db, user.id, "feishu_ask", detail=q[:200])
    card = build_card(q, answer, sources, settings.feishu_bot_name)
    send_card(chat_id, "chat_id", card)


def _anon_user(db) -> User:
    u = db.query(User).filter_by(username="feishu_anon").first()
    if not u:
        role = db.query(Role).filter_by(name="user").first()
        u = User(username="feishu_anon", role_id=role.id if role else 3)
        db.add(u)
        db.commit()
        db.refresh(u)
    return u


def _reply(msg, text: str) -> None:
    chat_id = getattr(msg, "chat_id", "")
    card = build_card("", text, [], settings.feishu_bot_name)
    send_card(chat_id, "chat_id", card)


def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1) -> None:
    try:
        _handle_message(data)
    except Exception:  # noqa: BLE001
        logger.exception("处理飞书消息异常")


def start_feishu_bot() -> None:
    logger.info("启动飞书长连接...")
    event_handler = (
        lark.EventDispatcherHandler.builder("" , "")
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1)
        .build()
    )
    cli = lark.ws.Client(
        settings.feishu_app_id,
        settings.feishu_app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.WARNING,
        domain=lark.FEISHU_DOMAIN,
    )
    cli.start()  # 阻塞，运行于守护线程

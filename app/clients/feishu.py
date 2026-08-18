"""飞书 API 客户端封装：发送互动卡片。"""
from __future__ import annotations

import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

from app.config import settings

logger = logging.getLogger("kb-bot.feishu")


def get_feishu_client() -> lark.Client:
    return (
        lark.Client.builder()
        .app_id(settings.feishu_app_id)
        .app_secret(settings.feishu_app_secret)
        .build()
    )


def send_card(receive_id: str, receive_id_type: str, card_json: str) -> bool:
    """向指定会话发送互动卡片。receive_id_type 通常为 'chat_id'。"""
    client = get_feishu_client()
    req = (
        CreateMessageRequest.builder()
        .receive_id_type(receive_id_type)
        .request_body(
            CreateMessageRequestBody.builder()
            .msg_type("interactive")
            .receive_id(receive_id)
            .content(card_json)
            .build()
        )
        .build()
    )
    resp = client.im.v1.message.create(req)
    if not resp.success():
        logger.error("飞书消息发送失败: %s %s", resp.code, resp.msg)
        return False
    return True

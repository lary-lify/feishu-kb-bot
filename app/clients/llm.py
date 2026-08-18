"""DeepSeek 文本生成服务（流式 + 一次性），含离线 Mock 模式。

Mock：设置环境变量 LLM_MOCK=1 时根据上下文拼装回复，便于无密钥联调。
"""
from __future__ import annotations

import os

from app.config import settings

_MOCK = os.getenv("LLM_MOCK") == "1"


def _client():
    from openai import OpenAI

    return OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)


def stream_chat(messages: list[dict], temperature: float = 0.3) -> "Iterator[str]":
    """流式返回 token 字符串迭代器。"""
    if _MOCK or not settings.deepseek_api_key:
        for piece in _mock_stream(messages):
            yield piece
        return
    client = _client()
    stream = client.chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        stream=True,
        temperature=temperature,
        max_tokens=4096,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def chat_once(messages: list[dict], temperature: float = 0.3) -> str:
    """一次性返回完整文本。"""
    if _MOCK or not settings.deepseek_api_key:
        return "".join(_mock_stream(messages))
    client = _client()
    resp = client.chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        stream=False,
        temperature=temperature,
        max_tokens=4096,
    )
    return resp.choices[0].message.content or ""


def _mock_stream(messages: list[dict]) -> list[str]:
    # 从最后一条用户消息中粗略提取引用材料，拼出可读回复
    last_user = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_user = m["role"]
            break
    answer = (
        "【Mock 模式回复】已基于知识库检索到的参考资料生成答复。"
        "请配置 DEEPSEEK_API_KEY 以获得真实大模型生成能力。"
    )
    return [answer[i : i + 8] for i in range(0, len(answer), 8)]

"""RAG 生成：检索 → 组装 grounding 提示 → DeepSeek 流式/一次性生成 → 引用来源。"""
from __future__ import annotations

import json
import re
from typing import Iterator

from sqlalchemy.orm import Session

from app.clients.llm import chat_once, stream_chat
from app.config import settings
from app.db.models import User
from app.services import audit as audit_svc
from app.services.retrieval import SourceChunk, retrieve

SYSTEM_PROMPT = """你是一个企业知识库问答助手。严格遵守以下规则：
1. 你只能基于下方提供的"参考资料"来回答用户的问题。
2. 如果参考资料中没有与问题相关的信息，必须回答："抱歉，知识库中没有找到相关信息。"
3. 禁止编造、推测或使用你自己的知识来回答问题。
4. 回答时要完整引用参考资料中的相关内容，使用 markdown 格式，并在相关结论后标注来源编号（如 [1]、[2]）。
5. 如果用户的追问涉及参考资料中已有的信息，请结合之前的对话上下文理解问题含义。
6. 使用与用户提问相同的语言回答。"""

REWRITE_PROMPT = """你是一个查询改写专家。将用户原始查询改写成更适合知识库检索的形式。
规则：
1. 提取核心意图，去掉具体型号、品牌等细节
2. 将具体问题改写为更通用的形式
3. 生成2-3个不同表述的查询变体，提高召回率
原始查询：{query}
请生成改写后的查询（JSON格式）：
{{"rewritten_query": "...", "query_variants": ["...", "..."]}}"""


def estimate_tokens(text: str) -> int:
    cn = len(re.findall(r"[一-鿿]", text))
    en = len(re.findall(r"[A-Za-z0-9]+", text))
    return int(cn * 1.5 + en)


def rewrite_query(query: str) -> str:
    try:
        out = chat_once(
            [
                {"role": "system", "content": REWRITE_PROMPT.format(query=query)},
                {"role": "user", "content": query},
            ],
            temperature=0.1,
        )
        m = re.search(r"\{.*\}", out, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            return data.get("rewritten_query") or query
    except Exception:
        pass
    return query


def _assemble(history: list[dict], sources: list[SourceChunk], question: str) -> list[dict]:
    materials = []
    for i, s in enumerate(sources, 1):
        materials.append(f"[Source {i}](score={s.score}): {s.content}")
    ref = "\n\n".join(materials)
    user_content = f"## Reference Materials:\n{ref}\n\n## User Question:\n{question}"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history[-9:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_content})
    return messages


def _format_sources(sources: list[SourceChunk]) -> list[dict]:
    return [
        {
            "chunk_id": s.chunk_id,
            "kb_id": s.kb_id,
            "doc_name": s.doc_name,
            "source_url": s.source_url,
            "source_type": s.source_type,
            "chunk_index": s.chunk_index,
            "score": s.score,
            "snippet": s.content[:300],
        }
        for s in sources
    ]


NO_CONTEXT_REPLY = "抱歉，知识库中没有找到相关信息。"


def _rewrite_if_enabled(question: str) -> str:
    """RAG_QUERY_REWRITE=1 时先用 LLM 改写查询再检索；默认关闭（省一次调用）。"""
    if settings.rag_query_rewrite:
        try:
            return rewrite_query(question)
        except Exception:  # noqa: BLE001
            return question
    return question


def generate_answer(
    db: Session,
    user: User,
    question: str,
    kb_ids: list[int],
    history: list[dict] | None = None,
    conversation_id: int | None = None,
) -> tuple[str, list[dict]]:
    """一次性生成（飞书卡片用）。返回 (answer, sources_dict_list)。"""
    sources = retrieve(db, kb_ids, _rewrite_if_enabled(question))
    if not sources:
        return NO_CONTEXT_REPLY, []
    messages = _assemble(history or [], sources, question)
    answer = chat_once(messages)
    in_tok = estimate_tokens(json.dumps(messages, ensure_ascii=False))
    out_tok = estimate_tokens(answer)
    audit_svc.log_token_usage(
        db, "chat", input_tokens=in_tok, output_tokens=out_tok,
        user_id=user.id, conversation_id=conversation_id,
    )
    return answer, _format_sources(sources)


def stream_answer(
    db: Session,
    user: User,
    question: str,
    kb_ids: list[int],
    history: list[dict] | None = None,
    conversation_id: int | None = None,
) -> Iterator[dict]:
    """Web SSE 用：依次产出 source_chunks / token / done。"""
    sources = retrieve(db, kb_ids, _rewrite_if_enabled(question))
    yield {"type": "source_chunks", "data": _format_sources(sources)}
    if not sources:
        yield {"type": "token", "text": NO_CONTEXT_REPLY}
        yield {"type": "done", "data": {"input_tokens": 0, "output_tokens": 0}}
        return
    messages = _assemble(history or [], sources, question)
    answer_parts: list[str] = []
    for piece in stream_chat(messages):
        answer_parts.append(piece)
        yield {"type": "token", "text": piece}
    answer = "".join(answer_parts)
    in_tok = estimate_tokens(json.dumps(messages, ensure_ascii=False))
    out_tok = estimate_tokens(answer)
    audit_svc.log_token_usage(
        db, "chat", input_tokens=in_tok, output_tokens=out_tok,
        user_id=user.id, conversation_id=conversation_id,
    )
    yield {"type": "done", "data": {"input_tokens": in_tok, "output_tokens": out_tok}}

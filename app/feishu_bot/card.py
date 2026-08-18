"""构造含引用来源的飞书互动卡片（返回 JSON 字符串）。"""
from __future__ import annotations

import json
from typing import Any


def build_card(question: str, answer: str, sources: list[dict], bot_name: str = "") -> str:
    elements: list[dict[str, Any]] = []

    # 问题回显
    q = question.strip().replace("\n", " ")
    elements.append(
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**❓ 您的问题：** {_escape(q)[:500]}",
            },
        }
    )
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "---"}})

    # 回答（截断过长文本，避免超出卡片字段上限）
    answer = (answer or "（无可用回答）")[:10000]
    elements.append(
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": answer},
        }
    )

    # 引用来源
    if sources:
        elements.append({"tag": "hr"})
        lines = ["**📎 参考来源**"]
        for i, s in enumerate(sources[:5], 1):
            name = s.get("doc_name") or "文档"
            idx = s.get("chunk_index")
            seg = f"第{idx}段" if idx is not None else ""
            label = f"{i}. 📄 {name}" + (f" · {seg}" if seg else "")
            url = s.get("source_url")
            if url:
                label += f"  [查看]({_safe_url(url)})"
            lines.append(label)
        elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}
        )
    else:
        elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": "_(未检索到相关来源)_"}}
        )

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": f"{bot_name or '客服助手'}回复"},
        },
        "elements": elements,
    }
    return json.dumps(card, ensure_ascii=False)


def _escape(text: str) -> str:
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _safe_url(url: str) -> str:
    """转义 markdown 链接中的破坏性字符，防止 URL 逃逸出 [text](url)。"""
    return (
        url.strip()
        .replace("(", "%28")
        .replace(")", "%29")
        .replace("]", "%5D")
        .replace(" ", "%20")
    )

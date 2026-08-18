"""文本分块：fixed_token（默认，字符近似+句边界微调+重叠）与 heading_level。"""
from __future__ import annotations

import re

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


def _split_sentences(text: str) -> list[str]:
    parts = _SENT_SPLIT.split(text)
    return [p for p in parts if p.strip()]


def _pack_sentences(sentences: list[str], chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    buf = ""
    for s in sentences:
        if not s.strip():
            continue
        if buf and len(buf) + len(s) > chunk_size:
            chunks.append(buf.strip())
            # 重叠：取末尾 overlap 字符作为新缓冲开头
            buf = buf[-overlap:] if overlap else ""
        buf += s
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


def chunk_fixed_token(text: str, chunk_size: int = 512, overlap: int = 128) -> list[str]:
    sentences = _split_sentences(text)
    if not sentences:
        # 无标点长文：硬切
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)] or [""]
    return _pack_sentences(sentences, chunk_size, overlap)


def chunk_heading_level(text: str, chunk_size: int = 512, overlap: int = 128) -> list[str]:
    """按 markdown 标题分节；单节过长时再按句子切分。每段带标题前缀。"""
    lines = text.split("\n")
    sections: list[tuple[str, str]] = []  # (heading, body)
    cur_heading = ""
    cur_body: list[str] = []
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if m:
            if cur_heading or cur_body:
                sections.append((cur_heading, "\n".join(cur_body)))
            cur_heading = m.group(2).strip()
            cur_body = []
        else:
            cur_body.append(line)
    if cur_heading or cur_body:
        sections.append((cur_heading, "\n".join(cur_body)))

    out: list[str] = []
    for heading, body in sections:
        if not body.strip():
            continue
        prefix = f"【{heading}】\n" if heading else ""
        if len(body) <= chunk_size:
            out.append(prefix + body.strip())
        else:
            for sub in chunk_fixed_token(body, chunk_size, overlap):
                out.append(prefix + sub)
    return out or [text[:chunk_size]]


_STRATEGIES = {
    "fixed_token": chunk_fixed_token,
    "heading_level": chunk_heading_level,
}


def chunk_text(text: str, strategy: str = "fixed_token",
               chunk_size: int = 512, overlap: int = 128) -> list[str]:
    fn = _STRATEGIES.get(strategy, chunk_fixed_token)
    chunks = fn(text, chunk_size, overlap)
    # 过滤空块
    return [c for c in chunks if c.strip()]

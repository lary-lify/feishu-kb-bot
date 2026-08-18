"""应用内 BM25 关键词检索（中文 jieba 分词 + rank_bm25）。

按知识库缓存分词结果；查询时合并可读 KB 的语料构建 BM25 并排序。
避免引入 PostgreSQL 中文分词扩展，保持单容器部署。
"""
from __future__ import annotations

import logging
import re

from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from app.db.models import Chunk

try:  # jieba 为可选依赖：中文分词质量更好；缺失时回退到轻量分词
    import jieba

    jieba.setLogLevel(logging.ERROR)
    _JIEBA = True
except Exception:  # pragma: no cover - 回退路径
    _JIEBA = False

_CJK = re.compile(r"[一-鿿]")
_WORD = re.compile(r"[A-Za-z0-9]+")

_KB_INDEX: dict[int, dict] = {}  # kb_id -> {ids, tokens, metas, bm25}
# kb_ids 组合 -> 合并索引 {ids, tokens, metas, bm25}，避免每次查询重建
_COMBINED_CACHE: dict[frozenset, dict] = {}
_COMBINED_CACHE_MAX = 32


def _tokenize(text: str) -> list[str]:
    if _JIEBA:
        return [t for t in jieba.lcut(text) if t.strip()]
    # 回退：英文/数字按词切，连续中文逐字切（BM25 在短文本仍可用）
    toks: list[str] = []
    for seg in _WORD.findall(text):
        toks.append(seg.lower())
    for ch in text:
        if _CJK.match(ch):
            toks.append(ch)
    return [t for t in toks if t.strip()]


def build_kb_index(db: Session, kb_id: int) -> None:
    ids: list[int] = []
    tokens: list[list[str]] = []
    metas: dict[int, str] = {}
    for c in db.query(Chunk).filter_by(kb_id=kb_id).all():
        ids.append(c.id)
        tokens.append(_tokenize(c.content))
        metas[c.id] = c.content
    bm25 = BM25Okapi(tokens) if tokens else None
    _KB_INDEX[kb_id] = {"ids": ids, "tokens": tokens, "metas": metas, "bm25": bm25}
    # 该库内容已变，失效所有组合缓存
    _COMBINED_CACHE.clear()


def rebuild_kb_index(db: Session, kb_id: int) -> None:
    build_kb_index(db, kb_id)


def rebuild_all(db: Session) -> None:
    from app.db.models import KB

    for kb in db.query(KB).all():
        build_kb_index(db, kb.id)


def _combined(db: Session, kb_ids: list[int]) -> dict:
    """获取 kb_ids 的合并索引（带缓存，上限防止组合爆炸）。"""
    key = frozenset(kb_ids)
    cached = _COMBINED_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_COMBINED_CACHE) >= _COMBINED_CACHE_MAX:
        _COMBINED_CACHE.clear()
    all_ids: list[int] = []
    all_tokens: list[list[str]] = []
    id_to_text: dict[int, str] = {}
    for kb_id in kb_ids:
        if kb_id not in _KB_INDEX:
            build_kb_index(db, kb_id)
        info = _KB_INDEX[kb_id]
        all_ids.extend(info["ids"])
        all_tokens.extend(info["tokens"])
        id_to_text.update(info["metas"])
    entry = {
        "ids": all_ids,
        "tokens": all_tokens,
        "metas": id_to_text,
        "bm25": BM25Okapi(all_tokens) if all_tokens else None,
    }
    _COMBINED_CACHE[key] = entry
    return entry


def bm25_search(db: Session, kb_ids: list[int], query: str, top_k: int = 30):
    """返回 [(chunk_id, score), ...] 按分数降序，仅限 kb_ids 内。"""
    q_tokens = _tokenize(query)
    entry = _combined(db, kb_ids)
    if not entry["tokens"]:
        return []
    scores = entry["bm25"].get_scores(q_tokens)
    ranked = sorted(zip(entry["ids"], scores), key=lambda x: x[1], reverse=True)
    return [(cid, float(s)) for cid, s in ranked[:top_k] if s > 0]

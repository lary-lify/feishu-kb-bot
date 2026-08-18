"""通义 text-embedding-v3 嵌入服务（含离线 Mock 模式）。

Mock：设置环境变量 EMBEDDING_MOCK=1 时返回确定性随机向量，便于无密钥联调。
"""
from __future__ import annotations

import hashlib
import os
import random

from app.config import settings

_MOCK = os.getenv("EMBEDDING_MOCK") == "1"


def _mock_embed(texts: list[str]) -> list[list[float]]:
    dim = settings.embedding_dim
    out = []
    for t in texts:
        seed = int(hashlib.md5(t.encode("utf-8")).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)
        vec = [rng.gauss(0, 1) for _ in range(dim)]
        norm = (sum(x * x for x in vec)) ** 0.5 or 1.0
        out.append([x / norm for x in vec])
    return out


def embed_texts(texts: list[str]) -> tuple[list[list[float]], int]:
    """批量嵌入，返回 (vectors, total_tokens)。批量上限 10。"""
    if not texts:
        return [], 0
    if _MOCK or not settings.dashscope_api_key:
        if not _MOCK and not settings.dashscope_api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY，且未开启 EMBEDDING_MOCK")
        return _mock_embed(texts), 0

    import dashscope
    from dashscope import TextEmbedding

    dashscope.api_key = settings.dashscope_api_key

    vectors: list[list[float]] = [[] for _ in texts]
    total_tokens = 0
    for i in range(0, len(texts), 10):
        batch = texts[i : i + 10]
        resp = TextEmbedding.call(model=settings.embedding_model, input=batch)
        if resp.status_code != 200:
            raise RuntimeError(f"通义嵌入调用失败: {resp.status_code} {resp.message}")
        for item in resp.output["embeddings"]:
            idx = item["text_index"] + i
            vectors[idx] = item["embedding"]
        total_tokens += int(resp.usage.get("total_tokens", 0))
    return vectors, total_tokens


def embed_query(text: str) -> list[float]:
    vecs, _ = embed_texts([text])
    return vecs[0]

"""纯逻辑/导入冒烟测试（无需 PostgreSQL 即可运行）。

运行： pip install pytest && pytest tests/ -q
（嵌入/生成相关测试需设置 EMBEDDING_MOCK=1 与 LLM_MOCK=1）
"""
import os

os.environ.setdefault("EMBEDDING_MOCK", "1")
os.environ.setdefault("LLM_MOCK", "1")

from app.services.chunking import chunk_text
from app.services.rag import _format_sources, estimate_tokens
from app.feishu_bot.card import build_card
from app.clients.embedding import embed_texts


def test_chunk_fixed_token():
    text = "。".join([f"这是第{i}句话用于测试分块逻辑是否按句边界切分且保持完整" for i in range(40)])
    chunks = chunk_text(text, "fixed_token", chunk_size=128, overlap=32)
    assert len(chunks) >= 2
    # 拼接后核心内容不丢失
    assert "第1句话" in chunks[0]


def test_chunk_heading_level():
    md = "# 售后政策\n七天无理由退货。\n# 保修\n一年质保。"
    chunks = chunk_text(md, "heading_level", chunk_size=512, overlap=64)
    assert any("售后政策" in c for c in chunks)
    assert any("保修" in c for c in chunks)


def test_card_with_sources():
    sources = [
        {"doc_name": "售后政策.pdf", "source_url": "https://kb/x.pdf", "chunk_index": 3, "score": 0.82},
    ]
    card = build_card("退货政策?", "根据政策可七天退货。", sources)
    assert "参考来源" in card
    assert "售后政策.pdf" in card
    assert "https://kb/x.pdf" in card


def test_estimate_tokens():
    assert estimate_tokens("hello world") >= 2
    assert estimate_tokens("你好世界") >= 4  # 中文按 1.5 token/字估算


def test_format_sources_shape():
    class S:  # 轻量桩
        chunk_id = 1; kb_id = 1; document_id = 1; chunk_index = 0
        content = "内容"; score = 0.9; doc_name = "d"; source_url = None; source_type = "file"
    out = _format_sources([S()])
    assert out[0]["doc_name"] == "d" and out[0]["score"] == 0.9


def test_embedding_mock_deterministic():
    v1, _ = embed_texts(["相同文本"])
    v2, _ = embed_texts(["相同文本"])
    assert len(v1[0]) == 1024
    assert v1[0] == v2[0]  # 同输入产生相同向量


def test_app_imports():
    import app.main as m
    assert hasattr(m, "app")
    routes = {r.path for r in m.app.routes}
    assert "/api/chat" in routes
    assert "/api/kbs" in routes
    assert "/" in routes

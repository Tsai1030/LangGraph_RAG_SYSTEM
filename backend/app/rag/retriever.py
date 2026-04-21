"""
retriever.py — Hybrid RAG 搜尋（向量 + BM25 + RRF 融合）
"""

from __future__ import annotations

import asyncio
import re

from rank_bm25 import BM25Okapi

from app.rag.vector_store import get_all_documents, search

# BM25 lazy singleton
_bm25: BM25Okapi | None = None
_corpus: list[dict] | None = None
_lock = asyncio.Lock()


def _tokenize(text: str) -> list[str]:
    """中英文混合 tokenizer：中文拆單字、英數字保留詞。"""
    return re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower())


async def _ensure_bm25() -> None:
    global _bm25, _corpus
    if _bm25 is not None:
        return
    async with _lock:
        if _bm25 is not None:
            return
        docs = await get_all_documents()
        _corpus = docs
        _bm25 = BM25Okapi([_tokenize(d["document"]) for d in docs])


def _rrf(
    vector_hits: list[dict],
    bm25_hits: list[dict],
    k: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion：合併兩個排序清單。"""
    scores: dict[str, float] = {}
    id_to_chunk: dict[str, dict] = {}

    for rank, chunk in enumerate(vector_hits):
        cid = chunk["id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        id_to_chunk[cid] = chunk

    for rank, chunk in enumerate(bm25_hits):
        cid = chunk["id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        id_to_chunk[cid] = chunk

    return [
        id_to_chunk[cid]
        for cid in sorted(scores, key=lambda x: scores[x], reverse=True)
    ]


async def retrieve(
    query: str,
    n_results: int = 8,
) -> list[dict]:
    """
    Hybrid 搜尋：向量 top-20 + BM25 top-20 → RRF → 回傳前 n_results 筆。
    """
    await _ensure_bm25()

    # 向量搜尋（取更多候選）
    vector_hits = await search(query, n_results=20)

    # BM25 搜尋
    tokens = _tokenize(query)
    bm25_scores = _bm25.get_scores(tokens)  # type: ignore[union-attr]
    top_indices = sorted(
        range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True
    )[:20]
    bm25_hits = [
        _corpus[i]  # type: ignore[index]
        for i in top_indices
        if bm25_scores[i] > 0
    ]

    merged = _rrf(vector_hits, bm25_hits)
    return merged[:n_results]


def format_sources(chunks: list[dict]) -> list[dict]:
    """從 chunks 提取來源資訊，去重後供前端 SourcesPanel 顯示。"""
    seen: set[tuple] = set()
    sources: list[dict] = []

    for chunk in chunks:
        meta = chunk.get("metadata", {})
        key = (meta.get("source_file", ""), meta.get("section_code", ""))
        if key in seen:
            continue
        seen.add(key)

        section = meta.get("parent_h3") or meta.get("parent_h2") or ""

        tags = meta.get("tags", [])
        if isinstance(tags, str):
            import json
            try:
                tags = json.loads(tags)
            except Exception:
                tags = [t.strip() for t in tags.split(",") if t.strip()]

        sources.append({
            "source_file": meta.get("source_file", ""),
            "section": section,
            "section_code": meta.get("section_code", ""),
            "tags": tags if isinstance(tags, list) else [],
        })

    return sources

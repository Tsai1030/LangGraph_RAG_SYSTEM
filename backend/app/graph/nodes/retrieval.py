"""
retrieval.py — RAG 檢索節點

呼叫 vector_store 搜尋相關 chunks，同時格式化來源資訊。
"""

from __future__ import annotations

import asyncio

from app.graph.state import GraphState
from app.rag.retriever import format_sources, retrieve, rrf


async def retriever(state: GraphState) -> dict:
    """
    從 ChromaDB 搜尋與 query 相關的 chunks。
    若有改寫版 query，雙路平行搜尋後以 RRF 融合：
    同時出現在兩組結果的 chunk 自動加分，確保 original 與 rewritten 兩個信號都有貢獻。
    """
    original_query = state["query"]
    retrieval_query = state.get("retrieval_query")

    if retrieval_query and retrieval_query.strip() != original_query.strip():
        rewritten_hits, original_hits = await asyncio.gather(
            retrieve(retrieval_query, n_results=8),
            retrieve(original_query, n_results=8),
        )
        chunks = rrf(rewritten_hits, original_hits)[:8]
    else:
        chunks = await retrieve(original_query, n_results=8)

    return {
        "retrieved_chunks": chunks,
        "sources": format_sources(chunks),
    }

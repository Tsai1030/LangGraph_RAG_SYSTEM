"""
retrieval.py — RAG 檢索節點

呼叫 vector_store 搜尋相關 chunks，同時格式化來源資訊。
"""

from __future__ import annotations

from app.graph.state import GraphState
from app.rag.retriever import format_sources, retrieve


async def retriever(state: GraphState) -> dict:
    """
    從 ChromaDB 搜尋與 query 相關的 chunks。
    雙路搜尋：原始 query 必跑；若 retrieval_query 已被改寫且不同，額外搜一次，
    兩份結果合併去重後取 top 8，確保原始意圖與文件語彙都能被覆蓋到。
    """
    original_query = state["query"]
    retrieval_query = state.get("retrieval_query")

    if retrieval_query and retrieval_query.strip() != original_query.strip():
        # CRAG rewriter 已改寫：優先用改寫版（目的性更強），再以原始 query 補滿
        primary = await retrieve(retrieval_query, n_results=8)
        secondary = await retrieve(original_query, n_results=8)
        seen_ids: set[str] = {c["id"] for c in primary}
        for chunk in secondary:
            if chunk["id"] not in seen_ids and len(primary) < 8:
                primary.append(chunk)
                seen_ids.add(chunk["id"])
        chunks = primary[:8]
    else:
        # 第一次搜尋：直接用原始 query
        chunks = await retrieve(original_query, n_results=8)

    return {
        "retrieved_chunks": chunks,
        "sources": format_sources(chunks),
    }

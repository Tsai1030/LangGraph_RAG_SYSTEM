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
    非同步節點（ChromaDB sync 呼叫已在 vector_store 中用 asyncio.to_thread 包裝）。
    """
    query = state["query"]
    chunks = await retrieve(query, n_results=5)

    return {
        "retrieved_chunks": chunks,
        "sources": format_sources(chunks),
    }

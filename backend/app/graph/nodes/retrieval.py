"""
retrieval.py — RAG 檢索節點

呼叫 vector_store 搜尋相關 chunks，同時格式化來源資訊。
"""

from __future__ import annotations

import asyncio

from app.graph.state import GraphState
from app.rag.retriever import format_sources, retrieve, rrf
from app.rag.session_store import search_session


async def retriever(state: GraphState) -> dict:
    """
    從 ChromaDB 搜尋與 query 相關的 chunks。
    若有改寫版 query，雙路平行搜尋後以 RRF 融合：
    同時出現在兩組結果的 chunk 自動加分，確保 original 與 rewritten 兩個信號都有貢獻。
    對話有上傳文件（document_refs 非空）時，每路查詢同時查 KB 與對話專屬
    session 索引，一併丟進 RRF 融合（session 搜尋失敗回 []，不影響 KB）。
    """
    original_query = state["query"]
    retrieval_query = state.get("retrieval_query")
    conversation_id = state["conversation_id"]
    has_docs = bool(state.get("document_refs"))

    async def search_all(query: str) -> list[list[dict]]:
        """單一 query 的所有檢索路：KB hybrid（+ session 向量，若有上傳文件）。"""
        tasks = [retrieve(query, n_results=8)]
        if has_docs:
            tasks.append(search_session(conversation_id, query, n_results=8))
        return await asyncio.gather(*tasks)

    if retrieval_query and retrieval_query.strip() != original_query.strip():
        rewritten_lists, original_lists = await asyncio.gather(
            search_all(retrieval_query),
            search_all(original_query),
        )
        chunks = rrf(*rewritten_lists, *original_lists)[:8]
    else:
        hit_lists = await search_all(original_query)
        chunks = rrf(*hit_lists)[:8] if len(hit_lists) > 1 else hit_lists[0]

    return {
        "retrieved_chunks": chunks,
        "sources": format_sources(chunks),
    }

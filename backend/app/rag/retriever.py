"""
retriever.py — RAG 搜尋邏輯封裝

功能：
- 呼叫 vector_store.search 取得相關 chunks
- 格式化來源資訊供前端顯示（去重）
"""

from __future__ import annotations

from app.rag.vector_store import search


async def retrieve(
    query: str,
    n_results: int = 5,
) -> list[dict]:
    """
    搜尋與 query 最相關的 chunks。

    Returns:
        list of {document, metadata, distance}
    """
    return await search(query, n_results=n_results)


def format_sources(chunks: list[dict]) -> list[dict]:
    """
    從 chunks 中提取來源資訊，去重後供前端 SourcesPanel 顯示。

    Returns:
        list of {source_file, section, section_code, tags}
    """
    seen: set[tuple] = set()
    sources: list[dict] = []

    for chunk in chunks:
        meta = chunk.get("metadata", {})
        key = (meta.get("source_file", ""), meta.get("section_code", ""))
        if key in seen:
            continue
        seen.add(key)

        # 選取最有意義的 section 名稱
        section = (
            meta.get("parent_h3")
            or meta.get("parent_h2")
            or ""
        )

        tags = meta.get("tags", [])
        if isinstance(tags, str):
            # ChromaDB 有時將 list 序列化成字串
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

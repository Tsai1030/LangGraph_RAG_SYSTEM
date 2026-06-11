"""
session_store.py — 對話專屬的暫存向量索引（聊天上傳文件用）

設計：
- 每個對話一個 ChromaDB collection（session_{conversation_id}），與 KB
  共用同一個 PersistentClient（vector_store.get_client）
- 上傳文件在 endpoint 內即時 chunk + embed 進此 collection；retriever
  查詢時與 KB 結果做 RRF 融合
- search_session 絕不向 graph 拋例外：任何錯誤回 []（KB 檢索照常進行）
- 生命週期：刪對話時刪 collection（best-effort）；每日清理 30 天以上的
  session collection（與上傳檔案清理同步）
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.config import settings
from app.rag.vector_store import _get_openai_client, get_client, get_embedding

logger = logging.getLogger(__name__)

_EMBED_BATCH_SIZE = 100  # 單次 embeddings API 的輸入筆數上限（避免超過 token 限制）


def _collection_name(conversation_id: str) -> str:
    return f"session_{conversation_id}"


async def add_chunks(
    conversation_id: str,
    chunks: list[dict],
    document_id: str,
) -> int:
    """把文件 chunks 批次 embed 後寫入對話專屬 collection，回傳寫入筆數。

    chunks 格式同 doc_chunker.chunk_markdown 輸出：[{document, metadata}]。
    id 用 {document_id}_{i}，同一文件重傳會覆蓋（upsert 語意由新 document_id 避開）。
    """
    if not chunks:
        return 0

    texts = [c["document"] for c in chunks]
    client = _get_openai_client()
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[start : start + _EMBED_BATCH_SIZE]
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=batch,
        )
        embeddings.extend(d.embedding for d in response.data)

    def _add() -> None:
        collection = get_client().get_or_create_collection(
            _collection_name(conversation_id),
            metadata={"created_at": int(time.time())},
        )
        collection.add(
            ids=[f"{document_id}_{i}" for i in range(len(chunks))],
            documents=texts,
            embeddings=embeddings,
            metadatas=[c["metadata"] for c in chunks],
        )

    await asyncio.to_thread(_add)
    logger.info(
        "[session_store] conv=%s doc=%s 寫入 %d chunks",
        conversation_id, document_id, len(chunks),
    )
    return len(chunks)


async def search_session(
    conversation_id: str,
    query: str,
    n_results: int = 8,
) -> list[dict[str, Any]]:
    """向量搜尋對話專屬 collection。回傳格式與 vector_store.search 相同。

    collection 不存在、為空或任何錯誤 → 回 []（記 log，不中斷 KB 檢索）。
    """
    try:
        collection = await asyncio.to_thread(
            get_client().get_collection, _collection_name(conversation_id)
        )
        query_embedding = await get_embedding(query)
        results = await asyncio.to_thread(
            collection.query,
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        logger.warning(
            "[session_store] conv=%s session 搜尋失敗（僅 KB 檢索）",
            conversation_id, exc_info=True,
        )
        return []

    return [
        {
            "id": id_,
            "document": doc,
            "metadata": meta,
            "distance": round(dist, 4),
        }
        for id_, doc, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]


def delete_session(conversation_id: str) -> None:
    """刪除對話專屬 collection（best-effort；不存在或失敗只記 log）。"""
    try:
        get_client().delete_collection(_collection_name(conversation_id))
        logger.info("[session_store] 已刪除 session collection conv=%s", conversation_id)
    except Exception:
        # collection 不存在是正常情況（多數對話沒上傳過文件）
        pass


def cleanup_old_sessions(max_age_days: int = 30) -> int:
    """刪除建立超過 max_age_days 的 session_* collections，回傳刪除數。"""
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    try:
        collections = get_client().list_collections()
    except Exception:
        logger.exception("[session_store] 列出 collections 失敗，跳過清理")
        return 0
    for col in collections:
        name = getattr(col, "name", "")
        if not name.startswith("session_"):
            continue
        created_at = (getattr(col, "metadata", None) or {}).get("created_at", 0)
        if created_at and created_at < cutoff:
            try:
                get_client().delete_collection(name)
                removed += 1
            except Exception:
                logger.warning("[session_store] 刪除 %s 失敗", name, exc_info=True)
    return removed

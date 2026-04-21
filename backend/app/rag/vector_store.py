"""
vector_store.py — ChromaDB 連線與向量搜尋介面

設計：
- ChromaDB PersistentClient 為同步 API，搜尋透過 asyncio.to_thread 包裝成非同步，
  避免阻塞 FastAPI event loop
- Singleton：整個 process 共用同一個 client / collection，不重複開啟
- Embedding 使用 OpenAI async client（text-embedding-3-small）
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import AsyncOpenAI

from app.config import settings

COLLECTION_NAME = "construction_knowledge"

# Singleton instances（lazy init）
_chroma_client: chromadb.PersistentClient | None = None
_collection = None
_openai_client: AsyncOpenAI | None = None


def _resolve_chroma_path() -> str:
    """
    若設定了 chroma_active_version（如 "v1"），
    回傳 chroma_versions/v1/ 路徑；否則回傳傳統 chroma_persist_path。
    """
    if settings.chroma_active_version:
        return str(
            Path(settings.chroma_versions_path) / settings.chroma_active_version
        )
    return settings.chroma_persist_path


def _get_collection():
    """取得 ChromaDB collection（lazy singleton）"""
    global _chroma_client, _collection
    if _collection is None:
        chroma_path = _resolve_chroma_path()
        _chroma_client = chromadb.PersistentClient(
            path=chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        _collection = _chroma_client.get_collection(COLLECTION_NAME)
    return _collection


def _get_openai_client() -> AsyncOpenAI:
    """取得 OpenAI async client（lazy singleton）"""
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


async def get_embedding(text: str) -> list[float]:
    """取得文字的 embedding 向量（async）"""
    client = _get_openai_client()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=[text],
    )
    return response.data[0].embedding


async def search(
    query: str,
    n_results: int = 5,
    where: dict | None = None,
) -> list[dict[str, Any]]:
    """
    向量相似度搜尋。

    Args:
        query:     查詢文字
        n_results: 回傳筆數（預設 5）
        where:     ChromaDB metadata filter（選填）

    Returns:
        list of {document: str, metadata: dict, distance: float}
    """
    query_embedding = await get_embedding(query)
    collection = _get_collection()

    kwargs: dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    # ChromaDB 為同步 API，用 asyncio.to_thread 包裝避免阻塞 event loop
    results = await asyncio.to_thread(collection.query, **kwargs)

    ids = results["ids"][0]
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    return [
        {
            "id": id_,
            "document": doc,
            "metadata": meta,
            "distance": round(dist, 4),
        }
        for id_, doc, meta, dist in zip(ids, docs, metas, dists)
    ]


async def get_all_documents() -> list[dict[str, Any]]:
    """載入所有 chunks，用於建立 BM25 索引。"""
    collection = _get_collection()
    results = await asyncio.to_thread(
        collection.get,
        include=["documents", "metadatas"],
    )
    return [
        {"id": id_, "document": doc, "metadata": meta}
        for id_, doc, meta in zip(
            results["ids"], results["documents"], results["metadatas"]
        )
    ]

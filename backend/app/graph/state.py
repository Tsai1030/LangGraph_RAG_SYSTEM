"""
state.py — LangGraph GraphState 定義

所有節點共享此狀態結構。
messages 使用 add_messages reducer，LangGraph 自動處理 append / remove 操作。
"""

from __future__ import annotations

from typing import Annotated, Optional
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class GraphState(TypedDict):
    # ── 對話識別 ─────────────────────────────────────────────
    conversation_id: str
    user_id: str

    # ── 訊息歷史（LangGraph 管理）────────────────────────────
    # add_messages reducer：新訊息自動 append；RemoveMessage 可刪除舊訊息
    messages: Annotated[list[BaseMessage], add_messages]

    # ── 當前查詢 ──────────────────────────────────────────────
    query: str

    # ── RAG 結果 ──────────────────────────────────────────────
    retrieved_chunks: list[dict]   # [{document, metadata, distance}]
    context: str                   # 組裝後的 context 字串

    # ── 意圖 ──────────────────────────────────────────────────
    intent: str                    # 'qa' | 'form_request'
    form_type: Optional[str]       # 'checklist' | 'report' | 'plan' | 'table'

    # ── 生成結果 ──────────────────────────────────────────────
    response: str
    form_data: Optional[dict]      # 結構化表單 JSON（form_request 時才有）
    sources: list[dict]            # 參考來源（供前端 SourcesPanel）

    # ── Compact 控制 ──────────────────────────────────────────
    is_compact_needed: bool
    token_count: int
    summary: Optional[str]         # 壓縮後的對話摘要

    # ── 檢索路由 ──────────────────────────────────────────────
    need_retrieval: bool             # True = 進行檢索；False = 跳過，直接回答

    # ── CRAG 閉環控制 ─────────────────────────────────────────
    retrieval_grade: str            # 'sufficient' | 'insufficient'
    retry_count: int                # 已重試次數（上限 2）
    retrieval_query: Optional[str]  # 檢索用查詢（rewriter 改寫後）；原始 query 永不覆寫

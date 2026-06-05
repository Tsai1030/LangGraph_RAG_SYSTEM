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
    grader_reason: Optional[str]             # grader 的判斷依據
    grader_missing_information: Optional[str]  # grader 指出缺少的資訊（供 rewriter 參考）

    # ── 靜態表單 ──────────────────────────────────────────────
    matched_forms: list[dict]       # registry 匹配的靜態表單 [{form_id, display_name, download_url}]
    form_explicit: bool             # True = 使用者明確索取表單檔案（直接下載），False = 主題相關詢問

    # ── 多輪表單延續 ───────────────────────────────────────────
    prev_form_data: Optional[dict]  # 最近一輪生成的表單（供延續生成時避免重複、保持格式一致）
    is_form_continuation: bool      # True = router 判定為延續上一輪表單，intent 直接 fast-path

    # ── 動態表單匯出 ───────────────────────────────────────────
    # intent=dynamic_form_export 時設定；form_exporter 節點讀取後產出 .xlsx / .csv
    export_format: Optional[str]    # 'xlsx' | 'csv'
    exported_form_file: Optional[dict]  # {form_id, display_name, download_url}（成功匯出後設）

    # ── 靜態表單填寫 session（多輪持久化）──────────────────────
    # 由 checkpointer 自動跨輪保留，form_template_loader / form_fill_collector / form_filler 共同維護
    # {
    #   "target_form_id": "010101",
    #   "collected": {"工程名稱": "...", "tbl0_r2_status": "V"},  # field key → value
    #   "status": "collecting" | "ready" | "completed",
    #   "filled_token": "<filename>"  # 完成填寫後的 docx 檔名（download endpoint 用）
    # }
    form_fill_session: Optional[dict]

    # ── VLM 圖片輸入 ──────────────────────────────────────────
    # image_refs：本輪要處理的圖片，只放輕量參照（base64 不進 state/checkpoint）
    #   [{"id": "<hex>", "path": "<磁碟路徑>", "mime": "image/png"}]
    # image_understanding：vision_intake 對圖片的文字解析（Stage 2 才會填值）
    image_refs: list[dict]
    image_understanding: Optional[str]

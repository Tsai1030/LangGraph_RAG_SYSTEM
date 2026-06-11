"""
builder.py — 組裝 LangGraph StateGraph

Graph 流程：
  START
    └─► vision_intake（有圖：Gemini 讀圖→解析併入 query；無圖：no-op 跳過）
    └─► compact_check
          ├─ is_compact_needed=True  ─► summarizer ─┐
          └─ is_compact_needed=False ───────────────┘
                                                     ▼
                                           unified_intent（單一 LLM 結構化輸出，決定 intent + need_retrieval）
                                            ├─ intent=static_form_download ──► [responder ∥ source_filter] → END
                                            ├─ intent=static_form_fill ──────► form_template_loader ─► form_fill_collector
                                            │                                     ├─ ready ─► form_filler ─► responder → END
                                            │                                     └─ collecting ─► responder → END
                                            ├─ intent=qa, need_retrieval=False ──► [responder ∥ source_filter] → END
                                            ├─ intent=qa, need_retrieval=True ───► retriever
                                            └─ intent=dynamic_form_generate / form_continuation ► retriever
                                                                                                    │
                                                                                              context_builder
                                                                                                    │
                                                                                          retrieval_grader
                                                                                            ├─ insufficient (<2 retries) ─► query_rewriter
                                                                                            │     ├─ 改寫成功 ──────────────► retriever（重新檢索）
                                                                                            │     └─ 改寫失敗(fallback原query) ► 終端路由（跳過重複檢索）
                                                                                            └─ sufficient / max retries ─► route_post_grader
                                                                                                                              ├─ form intents ─► form_structurer ─► [responder ∥ source_filter] → END
                                                                                                                              └─ qa ──────────► [responder ∥ source_filter] → END

  responder 與 source_filter 並行執行（fan-out / fan-in）：
    - responder：串流生成回答
    - source_filter：以 query + retrieved_chunks 評估相關來源（不依賴 response）

  static_form_fill 不走 source_filter（無檢索結果）。
"""

from __future__ import annotations

import logging
from typing import Union

from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)

from app.graph.nodes.compact import compact_check, summarizer
from app.graph.nodes.context import context_builder
from app.graph.nodes.form import form_structurer
from app.graph.nodes.form_exporter import form_exporter
from app.graph.nodes.form_fill import (
    form_fill_collector,
    form_filler,
    form_template_loader,
)
from app.graph.nodes.generation import responder
from app.graph.nodes.grader import query_rewriter, retrieval_grader
from app.graph.nodes.retrieval import retriever
from app.graph.nodes.source_filter import source_filter
from app.graph.nodes.unified_intent import unified_intent
from app.graph.nodes.vision import vision_intake
from app.graph.state import GraphState

_MAX_RETRIES = 2
_FORM_INTENTS = {"dynamic_form_generate", "form_continuation"}


def _route_compact(state: GraphState) -> str:
    """compact_check 後的條件路由"""
    return "summarizer" if state.get("is_compact_needed") else "unified_intent"


def _route_intent(state: GraphState) -> Union[str, list[str]]:
    """
    unified_intent 後的路由：
    - static_form_download → 並行直接回 responder ∥ source_filter（無需檢索）
    - static_form_fill → form_template_loader（進入填表流程）
    - dynamic_form_export → form_exporter（不打 LLM 直接轉檔）→ responder
    - 任何意圖 + need_retrieval=True → retriever（含 form 生成類）
    - 否則 → 並行 responder ∥ source_filter
    """
    intent = state.get("intent")
    if intent == "static_form_download":
        return ["responder", "source_filter"]
    if intent == "static_form_fill":
        return "form_template_loader"
    if intent == "dynamic_form_export":
        return "form_exporter"
    if state.get("need_retrieval", True):
        return "retriever"
    return ["responder", "source_filter"]


def _route_after_collector(state: GraphState) -> str:
    """
    form_fill_collector 後：session 進入 ready → form_filler；否則直接由 responder 追問。
    """
    session = state.get("form_fill_session") or {}
    return "form_filler" if session.get("status") == "ready" else "responder"


def _route_grader(state: GraphState) -> Union[str, list[str]]:
    """
    retrieval_grader 後的路由：
    - insufficient 且未達重試上限 → query_rewriter
    - 否則：依 intent 決定是否還需要 form_structurer
    """
    grade = state.get("retrieval_grade")
    retry = state.get("retry_count") or 0
    logger.info("[route_grader] grade=%s  retry_count=%d  max=%d", grade, retry, _MAX_RETRIES)
    if grade == "insufficient" and retry < _MAX_RETRIES:
        return "query_rewriter"

    if state.get("intent") in _FORM_INTENTS:
        return "form_structurer"
    return ["responder", "source_filter"]


def _route_rewriter(state: GraphState) -> Union[str, list[str]]:
    """
    query_rewriter 後的路由：
    - 改寫出新 query → retriever 重新檢索
    - 改寫失敗（fallback 回原 query）→ 跳過重複檢索，直接走與 _route_grader
      sufficient 分支相同的終端路由。retriever 對相同 query 會得到幾乎相同
      的結果，再 grade 一次只是白燒一輪 LLM；上一輪的 retrieved_chunks /
      context / sources 仍在 state，行為等同既有的 max-retries 出口。

    比較語意刻意與 retrieval.py 的雙路 RRF gate 一致（.strip() 不等式）——
    確保「會進 retriever 的」一定是 retriever 會做雙路融合的情況。
    註：第二次改寫若重複產出與第一次相同的「改寫版」query（非原 query），
    仍會再檢索一次；RRF 去重讓成本可接受，不另外加 state 偵測。
    """
    rewritten = (state.get("retrieval_query") or "").strip()
    if rewritten and rewritten != state["query"].strip():
        return "retriever"

    logger.info("[route_rewriter] 改寫 fallback 回原 query，跳過重複檢索")
    if state.get("intent") in _FORM_INTENTS:
        return "form_structurer"
    return ["responder", "source_filter"]


def build_graph(checkpointer=None):
    """
    建立並編譯 LangGraph StateGraph。

    Args:
        checkpointer: AsyncSqliteSaver 實例（對話狀態持久化）。
                      若為 None 則不持久化（測試用途）。
    Returns:
        CompiledStateGraph
    """
    graph = StateGraph(GraphState)

    # ── 加入節點 ────────────────────────────────────────────
    graph.add_node("vision_intake", vision_intake)
    graph.add_node("compact_check", compact_check)
    graph.add_node("summarizer", summarizer)
    graph.add_node("unified_intent", unified_intent)
    graph.add_node("retriever", retriever)
    graph.add_node("context_builder", context_builder)
    graph.add_node("retrieval_grader", retrieval_grader)
    graph.add_node("query_rewriter", query_rewriter)
    graph.add_node("form_structurer", form_structurer)
    graph.add_node("form_template_loader", form_template_loader)
    graph.add_node("form_fill_collector", form_fill_collector)
    graph.add_node("form_filler", form_filler)
    graph.add_node("form_exporter", form_exporter)
    graph.add_node("responder", responder)
    graph.add_node("source_filter", source_filter)

    # ── 加入邊 ──────────────────────────────────────────────

    # 入口：先過 vision_intake（有圖才讀圖→解析併入 query；無圖 no-op 直接過）
    graph.add_edge(START, "vision_intake")
    graph.add_edge("vision_intake", "compact_check")

    # compact_check → summarizer 或 unified_intent
    graph.add_conditional_edges("compact_check", _route_compact)

    # summarizer 完成後進 unified_intent
    graph.add_edge("summarizer", "unified_intent")

    # unified_intent → retriever（需檢索）或 [responder ∥ source_filter]（直接回應）
    graph.add_conditional_edges("unified_intent", _route_intent)

    # RAG 主流程
    graph.add_edge("retriever", "context_builder")

    # CRAG 閉環：context_builder → retrieval_grader → (rewriter→retriever) 或 終端路由
    # rewriter 改寫失敗（fallback 原 query）時跳過重複檢索直接走終端路由
    graph.add_edge("context_builder", "retrieval_grader")
    graph.add_conditional_edges("retrieval_grader", _route_grader)
    graph.add_conditional_edges("query_rewriter", _route_rewriter)

    # form_structurer → [responder ∥ source_filter] 並行
    graph.add_edge("form_structurer", "responder")
    graph.add_edge("form_structurer", "source_filter")

    # 填表流程：loader → collector → (filler 或 responder)
    graph.add_edge("form_template_loader", "form_fill_collector")
    graph.add_conditional_edges("form_fill_collector", _route_after_collector)
    graph.add_edge("form_filler", "responder")

    # 動態表單匯出：form_exporter → responder（短確認）
    graph.add_edge("form_exporter", "responder")

    # 並行分支匯入 END（LangGraph fan-in 自動等待兩者完成）
    graph.add_edge("responder", END)
    graph.add_edge("source_filter", END)

    return graph.compile(checkpointer=checkpointer)

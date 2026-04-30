"""
builder.py — 組裝 LangGraph StateGraph

Graph 流程：
  START
    └─► compact_check
          ├─ is_compact_needed=True  ─► summarizer ─┐
          └─ is_compact_needed=False ───────────────┘
                                                     ▼
                                           retrieval_router（LLM structured output: RouterDecision）
                                            ├─ form_explicit=True ─────────────────────────────────────────────► intent_classifier
                                            ├─ need_retrieval=True ─► retriever
                                            │    （is_form_continuation=True 時附帶 retrieval_topic 作為 retrieval_query）
                                            │                               │
                                            │                         context_builder
                                            │                               │
                                            │                        retrieval_grader（GraderOutput: decision/reason/missing）
                                            │                         ├─ sufficient ─────────────────────────────────────────────► │
                                            │                         │                                                            │ (loop ≤ 2)
                                            │                         └─ insufficient ─► query_rewriter ──────────────────────────┘
                                            │                               │ (sufficient OR 超過重試上限)
                                            └─ need_retrieval=False ─► intent_classifier
                                                                          ├─ form_explicit + matched_forms → [responder ∥ source_filter] → END
                                                                          ├─ form_request（有 chunks）─► form_structurer → [responder ∥ source_filter] → END
                                                                          ├─ form_request（無 chunks）─► retriever（補做）
                                                                          └─ qa ──────────────────────► [responder ∥ source_filter] → END

  responder 與 source_filter 並行執行（fan-out / fan-in）：
    - responder：串流生成回答
    - source_filter：以 query + retrieved_chunks 評估相關來源（不依賴 response）
"""

from __future__ import annotations

import logging
from typing import Union

from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)

from app.graph.nodes.compact import compact_check, summarizer
from app.graph.nodes.context import context_builder
from app.graph.nodes.form import form_structurer
from app.graph.nodes.generation import responder
from app.graph.nodes.grader import query_rewriter, retrieval_grader
from app.graph.nodes.intent import intent_classifier
from app.graph.nodes.retrieval import retriever
from app.graph.nodes.router import retrieval_router
from app.graph.nodes.source_filter import source_filter
from app.graph.state import GraphState

_MAX_RETRIES = 2


def _route_compact(state: GraphState) -> str:
    """compact_check 後的條件路由"""
    return "summarizer" if state.get("is_compact_needed") else "retrieval_router"


def _route_retrieval(state: GraphState) -> str:
    """retrieval_router 後的條件路由：需要檢索 → retriever；跳過 → intent_classifier"""
    return "retriever" if state.get("need_retrieval", True) else "intent_classifier"


def _route_intent(state: GraphState) -> Union[str, list[str]]:
    """
    intent_classifier 後的條件路由。

    靜態表單（form_explicit=True + matched_forms）→ [responder ∥ source_filter] 並行。
    動態表單（form_request，無靜態匹配）→ 有 chunks 進 form_structurer，否則先補 retriever。
    qa → [responder ∥ source_filter] 並行。
    """
    if state.get("intent") == "form_request":
        if state.get("form_explicit") and state.get("matched_forms"):
            return ["responder", "source_filter"]
        return "form_structurer" if state.get("retrieved_chunks") else "retriever"
    return ["responder", "source_filter"]


def _route_grader(state: GraphState) -> str:
    """retrieval_grader 後的條件路由：insufficient 且未超過重試上限 → 重寫查詢；其餘 → 繼續生成"""
    grade = state.get("retrieval_grade")
    retry = state.get("retry_count") or 0
    logger.info("[route_grader] grade=%s  retry_count=%d  max=%d", grade, retry, _MAX_RETRIES)
    if grade == "insufficient" and retry < _MAX_RETRIES:
        return "query_rewriter"
    return "intent_classifier"


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
    graph.add_node("compact_check", compact_check)
    graph.add_node("summarizer", summarizer)
    graph.add_node("retrieval_router", retrieval_router)
    graph.add_node("retriever", retriever)
    graph.add_node("context_builder", context_builder)
    graph.add_node("retrieval_grader", retrieval_grader)
    graph.add_node("query_rewriter", query_rewriter)
    graph.add_node("intent_classifier", intent_classifier)
    graph.add_node("form_structurer", form_structurer)
    graph.add_node("responder", responder)
    graph.add_node("source_filter", source_filter)

    # ── 加入邊 ──────────────────────────────────────────────

    # 入口
    graph.add_edge(START, "compact_check")

    # compact_check → summarizer 或 retrieval_router（條件邊）
    graph.add_conditional_edges("compact_check", _route_compact)

    # summarizer 完成後進 retrieval_router
    graph.add_edge("summarizer", "retrieval_router")

    # retrieval_router → retriever（需要）或 intent_classifier（跳過）
    graph.add_conditional_edges("retrieval_router", _route_retrieval)

    # RAG 主流程
    graph.add_edge("retriever", "context_builder")

    # CRAG 閉環：context_builder → retrieval_grader → (query_rewriter → retriever) 或 intent_classifier
    graph.add_edge("context_builder", "retrieval_grader")
    graph.add_conditional_edges("retrieval_grader", _route_grader)
    graph.add_edge("query_rewriter", "retriever")

    # intent_classifier → [responder ∥ source_filter] 並行（qa / form_explicit）
    #                   → form_structurer（form_request + chunks）
    #                   → retriever（form_request，無 chunks）
    graph.add_conditional_edges("intent_classifier", _route_intent)

    # form_structurer → [responder ∥ source_filter] 並行
    graph.add_edge("form_structurer", "responder")
    graph.add_edge("form_structurer", "source_filter")

    # 並行分支都接 END（LangGraph fan-in 自動等待兩者完成）
    graph.add_edge("responder", END)
    graph.add_edge("source_filter", END)

    return graph.compile(checkpointer=checkpointer)

"""
builder.py — 組裝 LangGraph StateGraph

Graph 流程：
  START
    └─► compact_check
          ├─ is_compact_needed=True  ─► summarizer ─┐
          └─ is_compact_needed=False ───────────────┘
                                                     ▼
                                           retrieval_router
                                            ├─ need_retrieval=True  ─► retriever
                                            │                               │
                                            │                         context_builder
                                            │                               │
                                            │                        retrieval_grader  ◄─────────────────┐
                                            │                         ├─ sufficient ───────────────────► │
                                            │                         │                                  │ (loop, max 2)
                                            │                         └─ insufficient ─► query_rewriter ─┘
                                            │                               │ (sufficient OR max retries)
                                            │                         intent_classifier
                                            │                          ├─ form_request ─► form_structurer ─► responder
                                            │                          └─ qa ───────────────────────────── ─► responder
                                            └─ need_retrieval=False ─► intent_classifier
                                                                          ├─ form_request（無 chunks）─► retriever（補做）
                                                                          ├─ form_request（有 chunks）─► form_structurer
                                                                          └─ qa ──────────────────────► responder
                                                                                                           │
                                                                                                          END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.graph.nodes.compact import compact_check, summarizer
from app.graph.nodes.context import context_builder
from app.graph.nodes.form import form_structurer
from app.graph.nodes.generation import responder
from app.graph.nodes.grader import query_rewriter, retrieval_grader
from app.graph.nodes.intent import intent_classifier
from app.graph.nodes.retrieval import retriever
from app.graph.nodes.router import retrieval_router
from app.graph.state import GraphState

_MAX_RETRIES = 2


def _route_compact(state: GraphState) -> str:
    """compact_check 後的條件路由"""
    return "summarizer" if state.get("is_compact_needed") else "retrieval_router"


def _route_retrieval(state: GraphState) -> str:
    """retrieval_router 後的條件路由：需要檢索 → retriever；跳過 → intent_classifier"""
    return "retriever" if state.get("need_retrieval", True) else "intent_classifier"


def _route_intent(state: GraphState) -> str:
    """
    intent_classifier 後的條件路由。
    form_request 且尚未有 retrieved_chunks（來自 skip 路徑）→ 補做 retriever。
    form_request 且已有 chunks → form_structurer。
    qa → responder。
    """
    if state.get("intent") == "form_request":
        return "form_structurer" if state.get("retrieved_chunks") else "retriever"
    return "responder"


def _route_grader(state: GraphState) -> str:
    """retrieval_grader 後的條件路由：insufficient 且未超過重試上限 → 重寫查詢；其餘 → 繼續生成"""
    if state.get("retrieval_grade") == "insufficient" and (state.get("retry_count") or 0) < _MAX_RETRIES:
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

    # ── 加入邊 ──────────────────────────────────────────────

    # 入口
    graph.add_edge(START, "compact_check")

    # compact_check → summarizer 或 retrieval_router（條件邊）
    graph.add_conditional_edges("compact_check", _route_compact)

    # summarizer 完成後進 retrieval_router
    graph.add_edge("summarizer", "retrieval_router")

    # retrieval_router → retriever（需要）或 responder（跳過）
    graph.add_conditional_edges("retrieval_router", _route_retrieval)

    # RAG 主流程
    graph.add_edge("retriever", "context_builder")

    # CRAG 閉環：context_builder → retrieval_grader → (query_rewriter → retriever) 或 intent_classifier
    graph.add_edge("context_builder", "retrieval_grader")
    graph.add_conditional_edges("retrieval_grader", _route_grader)
    graph.add_edge("query_rewriter", "retriever")

    # intent_classifier → form_structurer 或 responder（條件邊）
    graph.add_conditional_edges("intent_classifier", _route_intent)

    # form_structurer 完成後進 responder（讓 responder 加上表單說明文字）
    graph.add_edge("form_structurer", "responder")

    # responder → END
    graph.add_edge("responder", END)

    return graph.compile(checkpointer=checkpointer)

"""
builder.py — 組裝 LangGraph StateGraph

Graph 流程：
  START
    └─► compact_check
          ├─ is_compact_needed=True  ─► summarizer ─► retriever
          └─ is_compact_needed=False ─────────────► retriever
                                                       │
                                                  context_builder
                                                       │
                                                 intent_classifier
                                                  ├─ form_request ─► form_structurer ─► responder
                                                  └─ qa ───────────────────────────── ─► responder
                                                                                           │
                                                                                          END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.graph.nodes.compact import compact_check, summarizer
from app.graph.nodes.context import context_builder
from app.graph.nodes.form import form_structurer
from app.graph.nodes.generation import responder
from app.graph.nodes.intent import intent_classifier
from app.graph.nodes.retrieval import retriever
from app.graph.state import GraphState


def _route_compact(state: GraphState) -> str:
    """compact_check 後的條件路由"""
    return "summarizer" if state.get("is_compact_needed") else "retriever"


def _route_intent(state: GraphState) -> str:
    """intent_classifier 後的條件路由"""
    return "form_structurer" if state.get("intent") == "form_request" else "responder"


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
    graph.add_node("retriever", retriever)
    graph.add_node("context_builder", context_builder)
    graph.add_node("intent_classifier", intent_classifier)
    graph.add_node("form_structurer", form_structurer)
    graph.add_node("responder", responder)

    # ── 加入邊 ──────────────────────────────────────────────

    # 入口
    graph.add_edge(START, "compact_check")

    # compact_check → summarizer 或 retriever（條件邊）
    graph.add_conditional_edges("compact_check", _route_compact)

    # summarizer 完成後繼續進 retriever
    graph.add_edge("summarizer", "retriever")

    # RAG 主流程
    graph.add_edge("retriever", "context_builder")
    graph.add_edge("context_builder", "intent_classifier")

    # intent_classifier → form_structurer 或 responder（條件邊）
    graph.add_conditional_edges("intent_classifier", _route_intent)

    # form_structurer 完成後進 responder（讓 responder 加上表單說明文字）
    graph.add_edge("form_structurer", "responder")

    # responder → END
    graph.add_edge("responder", END)

    return graph.compile(checkpointer=checkpointer)

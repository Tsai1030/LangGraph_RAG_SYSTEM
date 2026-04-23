"""
grader.py — CRAG 閉環節點

retrieval_grader：評估 retrieved context 是否足以回答問題。
query_rewriter：若不足，將 query 改寫為更貼近文件語言的版本後重新檢索。
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.graph.state import GraphState

_GRADER_SYSTEM = """\
你是一位營造業知識庫的檢索品質評估員。
判斷提供的參考文件是否足以回答使用者的問題。
只輸出 SUFFICIENT 或 INSUFFICIENT，不要輸出其他內容。"""

_REWRITER_SYSTEM = """\
你是營造業知識庫的查詢改寫助理。
將使用者的問題改寫為更接近工程規範、法規文件用語的查詢，以利精確檢索。
只輸出改寫後的查詢字串，不要輸出其他內容。"""


async def retrieval_grader(state: GraphState) -> dict:
    """
    評估目前 context 是否足以回答問題。
    回傳 retrieval_grade: 'sufficient' | 'insufficient'
    """
    query = state.get("rewritten_query") or state["query"]
    context = state.get("context", "")

    # context 完全空白直接判 insufficient，不浪費 LLM 呼叫
    if not context or context == "（無相關文件）":
        return {"retrieval_grade": "insufficient"}

    llm = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key, temperature=0)
    result = await llm.ainvoke([
        SystemMessage(content=_GRADER_SYSTEM),
        HumanMessage(content=f"問題：{query}\n\n參考文件（前 800 字）：\n{context[:800]}"),
    ])

    grade = "sufficient" if "SUFFICIENT" in result.content.upper() else "insufficient"
    return {"retrieval_grade": grade}


async def query_rewriter(state: GraphState) -> dict:
    """
    將 query 改寫為更貼近文件語言的版本。
    同時遞增 retry_count，並更新 query 供下一輪 retriever 使用。
    """
    original = state.get("rewritten_query") or state["query"]
    retry_count = state.get("retry_count") or 0

    llm = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key, temperature=0)
    result = await llm.ainvoke([
        SystemMessage(content=_REWRITER_SYSTEM),
        HumanMessage(content=original),
    ])

    rewritten = result.content.strip()
    return {
        "rewritten_query": rewritten,
        "query": rewritten,          # 更新 state["query"] 讓 retriever 直接使用
        "retry_count": retry_count + 1,
    }

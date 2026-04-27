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
    評估目前 retrieved_chunks 是否足以回答問題。
    每個 chunk 取「來源標頭 + 前 300 字」，涵蓋全部 chunks 而非只看 context 前段。
    """
    query = state.get("retrieval_query") or state["query"]
    chunks = state.get("retrieved_chunks", [])

    if not chunks:
        return {"retrieval_grade": "insufficient"}

    # 每個 chunk 取標頭 + 前 300 字，讓 grader 看到所有 chunks 的代表性內容
    previews: list[str] = []
    for i, chunk in enumerate(chunks[:5]):
        meta = chunk.get("metadata", {})
        source = meta.get("source_file", "")
        h2 = meta.get("parent_h2", "")
        header = f"[{i + 1}]"
        if source:
            header += f" 【{source}】"
        if h2:
            header += f"【{h2}】"
        content = chunk.get("document", "")[:300]
        previews.append(f"{header}\n{content}")

    grader_context = "\n\n".join(previews)

    llm = ChatOpenAI(model=settings.grader_model, api_key=settings.openai_api_key, temperature=0)
    result = await llm.ainvoke([
        SystemMessage(content=_GRADER_SYSTEM),
        HumanMessage(content=f"問題：{query}\n\n參考文件片段（每份取前300字）：\n{grader_context}"),
    ])

    grade = "sufficient" if "SUFFICIENT" in result.content.upper() else "insufficient"
    return {"retrieval_grade": grade}


async def query_rewriter(state: GraphState) -> dict:
    """
    將查詢改寫為更貼近文件語言的版本。
    只寫入 retrieval_query，原始 query 永不覆寫。
    """
    # 若已有改寫版本則繼續改寫，否則從原始 query 開始
    current = state.get("retrieval_query") or state["query"]
    retry_count = state.get("retry_count") or 0

    llm = ChatOpenAI(model=settings.grader_model, api_key=settings.openai_api_key, temperature=0)
    result = await llm.ainvoke([
        SystemMessage(content=_REWRITER_SYSTEM),
        HumanMessage(content=current),
    ])

    return {
        "retrieval_query": result.content.strip(),
        "retry_count": retry_count + 1,
    }

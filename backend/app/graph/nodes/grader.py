"""
grader.py — CRAG 閉環節點

retrieval_grader：評估 retrieved context 是否足以回答問題。
query_rewriter：若不足，將 query 改寫為更貼近文件語言的版本後重新檢索。
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.graph.state import GraphState

logger = logging.getLogger(__name__)

_GRADER_SYSTEM = """\
你是一位營造業知識庫的檢索品質評估員。
根據問題類型，套用對應的判斷標準，決定文件是否足以回答。

【第一步：判斷問題類型】
A. 枚舉型：包含「有幾種/幾級/幾類/有哪些/列出」
B. 流程型：包含「流程/步驟/如何辦理/怎麼做」
C. 定義/說明型：包含「是什麼/定義/規定/說明/標準」

【第二步：套用對應標準】
A. 枚舉型 → SUFFICIENT 條件：文件明確列出全部項目或提供總數；若只列出部分而無總數，判 INSUFFICIENT
B. 流程型 → SUFFICIENT 條件：文件涵蓋該流程的主要步驟；細節不完整但主軸清楚可判 SUFFICIENT
C. 定義/說明型 → SUFFICIENT 條件：文件有直接的說明或數字；主題相關但無直接答案判 INSUFFICIENT

【共通 INSUFFICIENT 條件】
- 文件主題與問題完全不相關

只輸出 SUFFICIENT 或 INSUFFICIENT，不要輸出其他內容。"""

_REWRITER_SYSTEM = """\
你是營造業知識庫的查詢改寫助理。
將使用者的問題改寫為適合搜尋工程規範文件的「關鍵字查詢」。

改寫原則：
1. 去除問句語氣詞（有幾種、是什麼、如何、怎麼、哪些、幾個、多少等）
2. 保留問題的核心主題詞，並根據主題的語境補充正式的修飾語
   - 若主題涉及金額、費用、預算 → 補充金額相關修飾詞
   - 若主題涉及分類、等級、種類 → 補充分類依據（標準、條件等）
   - 若主題涉及作業流程 → 補充流程的執行主體或適用範圍
3. 輸出 4–10 個字的名詞短語，不要輸出完整句子
4. 以工程規範文件最可能使用的正式術語輸出，避免口語化

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

    content = result.content.upper().strip()
    if "INSUFFICIENT" in content:
        grade = "insufficient"
    elif "SUFFICIENT" in content:
        grade = "sufficient"
    else:
        grade = "insufficient"  # 無法判斷時保守地觸發重試
    logger.info("[retrieval_grader] grade=%s  raw='%s'  query='%s'", grade, result.content.strip(), query[:60])
    return {"retrieval_grade": grade}


async def query_rewriter(state: GraphState) -> dict:
    """
    將查詢改寫為更貼近文件語言的關鍵字短語。
    永遠以原始 query 為基礎改寫，避免多次 retry 時語意漂移。
    """
    original_query = state["query"]
    retry_count = state.get("retry_count") or 0

    llm = ChatOpenAI(model=settings.grader_model, api_key=settings.openai_api_key, temperature=0)
    result = await llm.ainvoke([
        SystemMessage(content=_REWRITER_SYSTEM),
        HumanMessage(content=original_query),
    ])

    rewritten = result.content.strip()
    logger.info("[query_rewriter] retry=%d  '%s' → '%s'", retry_count + 1, original_query, rewritten)

    return {
        "retrieval_query": rewritten,
        "retry_count": retry_count + 1,
    }

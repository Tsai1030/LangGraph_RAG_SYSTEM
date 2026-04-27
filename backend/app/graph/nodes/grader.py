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
嚴格判斷提供的參考文件能否**完整且精確**地回答使用者的問題。

判斷標準（必須全部符合才能輸出 SUFFICIENT）：
- 若問題問「有幾種／幾級／幾類」，文件必須明確列出**全部**種類或級別
- 若問題問流程或步驟，文件必須涵蓋**完整**流程，而非片段
- 若問題問金額、條件或門檻，文件必須提供**明確數字或標準**
- 若文件只有部分相關內容、只提到部分項目、或僅為周邊資訊，一律判為 INSUFFICIENT

只輸出 SUFFICIENT 或 INSUFFICIENT，不要輸出其他內容。"""

_REWRITER_SYSTEM = """\
你是營造業知識庫的查詢改寫助理。
將使用者的問題改寫為適合搜尋工程規範文件的「關鍵字查詢」。

改寫規則：
1. 去除問句語氣詞（有幾種、是什麼、如何、怎麼、哪些、幾個等）
2. 展開核心術語，務必補齊修飾語：
   - 「分級」必須展開為「金額分級」
   - 「採購」必須展開為「採購案件」
   - 「流程」相關必須加上對象（例如：二級以上採購案件辦理流程）
3. 輸出 4–10 個字的名詞短語，不要輸出完整句子
4. 以文件最可能使用的正式術語組合輸出

範例：
- 採購分級有幾種 → 採購案件金額分級
- 採購怎麼分類 → 採購案件金額分類標準
- 二級採購流程 → 二級以上採購案件辦理流程

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

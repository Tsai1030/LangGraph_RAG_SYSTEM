"""
grader.py — CRAG 閉環節點

retrieval_grader：評估 retrieved context 是否足以回答問題，輸出結構化 GraderOutput。
query_rewriter：若不足，將 query 改寫為更貼近文件語言的版本後重新檢索。
"""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.state import GraphState

logger = logging.getLogger(__name__)


class GraderOutput(BaseModel):
    decision: Literal["sufficient", "insufficient"]
    reason: str = Field(description="一句話說明判斷依據")
    missing_information: str = Field(
        default="",
        description="缺少的資訊描述（decision=insufficient 時填寫，sufficient 時留空）",
    )


_GRADER_SYSTEM = """\
你是一位營造業知識庫的檢索品質評估員。
根據問題類型，套用對應的判斷標準，決定文件是否足以回答。

【第一步：判斷問題類型】
A. 枚舉型：包含「有幾種/幾級/幾類/有哪些/列出」
B. 流程型：包含「流程/步驟/如何辦理/怎麼做」
C. 定義/說明型：包含「是什麼/定義/規定/說明/標準」

【第二步：套用對應標準】
A. 枚舉型 → sufficient 條件：文件明確列出全部項目或提供總數；若只列出部分而無總數，判 insufficient
B. 流程型 → sufficient 條件：文件涵蓋該流程的主要步驟；細節不完整但主軸清楚可判 sufficient
C. 定義/說明型 → sufficient 條件：文件有直接的說明或數字；主題相關但無直接答案判 insufficient

【共通 insufficient 條件】
- 文件主題與問題完全不相關

判 insufficient 時，請在 missing_information 欄位具體說明缺少哪類資訊（例如「缺少採購金額分級的完整列表」）。"""

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
    使用結構化輸出（GraderOutput），避免自由文字解析的不穩定性。
    """
    query = state.get("retrieval_query") or state["query"]
    chunks = state.get("retrieved_chunks", [])

    if not chunks:
        return {
            "retrieval_grade": "insufficient",
            "grader_reason": "無檢索結果",
            "grader_missing_information": "未能取得任何相關文件片段",
        }

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

    llm = ChatOpenAI(
        model=settings.grader_model, api_key=settings.openai_api_key, temperature=0
    ).with_structured_output(GraderOutput)

    result: GraderOutput = await llm.ainvoke([
        SystemMessage(content=_GRADER_SYSTEM),
        HumanMessage(content=f"問題：{query}\n\n參考文件片段（每份取前300字）：\n{grader_context}"),
    ])

    logger.info(
        "[retrieval_grader] decision=%s  reason='%s'  missing='%s'  query='%s'",
        result.decision,
        result.reason,
        result.missing_information,
        query[:60],
    )

    return {
        "retrieval_grade": result.decision,
        "grader_reason": result.reason,
        "grader_missing_information": result.missing_information,
    }


async def query_rewriter(state: GraphState) -> dict:
    """
    將查詢改寫為更貼近文件語言的關鍵字短語。
    若 grader 有提供 missing_information，將其作為改寫的上下文。
    永遠以原始 query 為基礎改寫，避免多次 retry 時語意漂移。
    """
    original_query = state["query"]
    retry_count = state.get("retry_count") or 0
    missing_info = state.get("grader_missing_information") or ""

    if missing_info:
        human_content = f"原始問題：{original_query}\n\n檢索評估指出缺少：{missing_info}"
    else:
        human_content = original_query

    llm = ChatOpenAI(model=settings.grader_model, api_key=settings.openai_api_key, temperature=0)
    result = await llm.ainvoke([
        SystemMessage(content=_REWRITER_SYSTEM),
        HumanMessage(content=human_content),
    ])

    rewritten = result.content.strip()
    logger.info(
        "[query_rewriter] retry=%d  '%s' → '%s'  (missing: '%s')",
        retry_count + 1,
        original_query,
        rewritten,
        missing_info[:60] if missing_info else "",
    )

    return {
        "retrieval_query": rewritten,
        "retry_count": retry_count + 1,
    }

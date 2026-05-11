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
from app.prompts import get_prompt

logger = logging.getLogger(__name__)


class GraderOutput(BaseModel):
    decision: Literal["sufficient", "insufficient"]
    reason: str = Field(description="一句話說明判斷依據")
    missing_information: str = Field(
        default="",
        description="缺少的資訊描述（decision=insufficient 時填寫，sufficient 時留空）",
    )


# rewriter 失敗訊號：LLM 放棄改寫時常見的描述性詞彙；命中即視為改寫失敗，fallback 回原 query
_REWRITER_FAILURE_SIGNALS = ("未明", "無主題", "無法", "不確定", "無相關", "不清楚", "無關")


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
        SystemMessage(content=get_prompt("grader")),
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
        SystemMessage(content=get_prompt("rewriter")),
        HumanMessage(content=human_content),
    ])

    rewritten = result.content.strip()

    # Sanity check：擋掉 LLM 放棄改寫時的垃圾輸出，避免污染下次檢索
    fallback_reason = None
    if not rewritten:
        fallback_reason = "empty"
    elif any(sig in rewritten for sig in _REWRITER_FAILURE_SIGNALS):
        fallback_reason = "failure_signal"
    elif len(rewritten) > 40:
        # 改寫後過長代表 LLM 沒照「4–10 字短語」格式輸出，多半是說明文字
        fallback_reason = "too_long"

    if fallback_reason:
        logger.warning(
            "[query_rewriter] fallback (%s)  retry=%d  '%s' → '%s'  使用原始 query",
            fallback_reason,
            retry_count + 1,
            original_query,
            rewritten,
        )
        rewritten = original_query
    else:
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

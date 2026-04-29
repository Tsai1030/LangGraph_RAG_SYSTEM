"""
router.py — 檢索路由節點

retrieval_router：
1. 執行靜態表單比對（form_lookup），判斷是否為明確表單下載請求
2. 否則，使用 LLM structured output 一次判斷：
   - need_retrieval：是否需要知識庫檢索
   - is_form_continuation：是否為延續表單生成（帶 retrieval_topic 與 reason）
"""

from __future__ import annotations

from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.state import GraphState
from app.rag.form_lookup import is_explicit_form_request, lookup_forms

_MAX_HISTORY_TURNS = 3


class RouterDecision(BaseModel):
    need_retrieval: bool = Field(
        description="是否需要從知識庫進行文件檢索"
    )
    is_form_continuation: bool = Field(
        description="是否為延續上一輪表單生成的請求（如：再生成幾組、多出幾題）"
    )
    retrieval_topic: Optional[str] = Field(
        default=None,
        description="若 is_form_continuation=True，填入應用於檢索的主題詞（從對話歷史推斷）；否則為 null",
    )
    reason: str = Field(description="一句話說明判斷依據")


_ROUTER_SYSTEM = """\
你是一位對話分析助理，負責同時判斷兩件事並以 JSON 回傳。

【need_retrieval】是否需要知識庫檢索：
- True（需要）：詢問技術規範、法規、施工流程、材料規格、生成任何表單或檢核表、涉及新主題
- False（不需要）：改寫或重新說明前一輪回答、針對前一輪細節的追問、致謝或純確認

【is_form_continuation】是否為延續上一輪表單生成的請求：
- True 需同時滿足：
  a. 使用者訊息顯示想繼續或增加表單內容（如「再生成五組」「多出幾題」「繼續做」「再來幾個」）
  b. 補充資訊標示「前一輪有生成過表單」
- 若為 True：
  - retrieval_topic 填入從對話推斷的表單主題（例如「新人訓練安全是非題」）
  - need_retrieval 必須為 True
- 若為 False，retrieval_topic 填 null

【reason】一句話說明你的判斷依據（20 字以內）。

判斷原則：有任何不確定，need_retrieval 輸出 True。"""


async def retrieval_router(state: GraphState) -> dict:
    """
    1. 先做靜態表單比對：明確索取靜態表單 → 跳過 RAG
    2. 否則呼叫 LLM structured output，一次判斷：
       - need_retrieval
       - is_form_continuation（若 True 附帶 retrieval_topic）
    """
    query = state["query"]

    # ── 靜態表單比對（每次都跑，與 need_retrieval 無關）──────
    matched_forms = lookup_forms(query)
    form_explicit = is_explicit_form_request(query) if matched_forms else False

    if form_explicit and matched_forms:
        return {
            "need_retrieval": False,
            "matched_forms": matched_forms,
            "form_explicit": True,
        }

    # ── LLM 路由判斷 ──────────────────────────────────────────
    messages = state.get("messages", [])
    prior = [m for m in messages[:-1] if isinstance(m, (HumanMessage, AIMessage))]
    recent = prior[-(_MAX_HISTORY_TURNS * 2):]

    # 快速路徑：沒有先前 AI 回應 → 必須檢索，不可能是延續
    if not any(isinstance(m, AIMessage) for m in recent):
        return {
            "need_retrieval": True,
            "matched_forms": matched_forms,
            "form_explicit": False,
        }

    # 組裝對話歷史
    history_lines: list[str] = []
    for msg in recent:
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
            history_lines.append(f"使用者：{msg.content}")
        elif isinstance(msg, AIMessage) and isinstance(msg.content, str):
            history_lines.append(f"AI 助理：{msg.content[:400]}")
    history_text = "\n".join(history_lines)

    # 前一輪表單狀態（提示 LLM 是否可能為延續）
    prev_form_data = state.get("prev_form_data")
    prev_form_hint = (
        f"前一輪有生成過表單（標題：{prev_form_data.get('title', '未知')}）"
        if prev_form_data
        else "前一輪無生成表單"
    )

    llm = ChatOpenAI(
        model=settings.grader_model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).with_structured_output(RouterDecision)

    decision: RouterDecision = await llm.ainvoke([
        SystemMessage(content=_ROUTER_SYSTEM),
        HumanMessage(content=(
            f"對話歷史：\n{history_text}\n\n"
            f"當前問題：{query}\n\n"
            f"補充資訊：{prev_form_hint}"
        )),
    ])

    is_continuation = (
        decision.is_form_continuation
        and prev_form_data is not None
        and bool(decision.retrieval_topic)
    )

    result: dict = {
        "need_retrieval": decision.need_retrieval,
        "matched_forms": matched_forms,
        "form_explicit": False,
        "is_form_continuation": is_continuation,
    }

    # 延續表單：設 retrieval_query 並強制做 retrieval
    if is_continuation:
        result["retrieval_query"] = decision.retrieval_topic
        result["need_retrieval"] = True

    return result

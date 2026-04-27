"""
router.py — 檢索路由節點

retrieval_router：
1. 執行靜態表單比對（form_lookup），判斷是否為明確表單下載請求
2. 若是明確靜態表單請求 → need_retrieval=False，直接進 intent_classifier
3. 否則判斷是否需要從知識庫進行文件檢索
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.graph.state import GraphState
from app.rag.form_lookup import is_explicit_form_request, lookup_forms

_ROUTER_SYSTEM = """\
你是一位檢索決策助理，負責判斷是否需要從知識庫進行文件檢索。

必須檢索（輸出 YES）：
- 詢問技術規範、法規、施工流程、材料規格等專業知識
- 請求生成表單、檢核表、報告等文件
- 涉及當前對話未提及的新主題或新問題

可跳過檢索（輸出 NO）：
- 明確要求改寫或重新說明前一輪回答（例如：「能說得更清楚嗎？」「換個方式說明」「用簡單的說法」）
- 針對前一輪回答某個細節的追問（例如：「你剛說的第一點是什麼意思？」「那個部分能展開嗎？」）
- 致謝或純確認（例如：「好的，謝謝」「我了解了」）

判斷原則：若有任何不確定，輸出 YES。
只輸出 YES 或 NO，不要輸出其他內容。"""

_MAX_HISTORY_TURNS = 3


async def retrieval_router(state: GraphState) -> dict:
    """
    1. 先做靜態表單比對：若使用者明確索取靜態表單 → 直接跳過檢索
    2. 否則判斷是否需要從知識庫檢索文件
    """
    query = state["query"]

    # ── 靜態表單比對（每次都跑，與 need_retrieval 無關）─────
    matched_forms = lookup_forms(query)
    form_explicit = is_explicit_form_request(query) if matched_forms else False

    # 明確索取靜態表單 → 跳過 RAG 直接進 intent_classifier
    if form_explicit and matched_forms:
        return {
            "need_retrieval": False,
            "matched_forms": matched_forms,
            "form_explicit": True,
        }

    # ── 以下為一般檢索路由邏輯 ────────────────────────────
    messages = state.get("messages", [])
    prior = [m for m in messages[:-1] if isinstance(m, (HumanMessage, AIMessage))]
    recent = prior[-(_MAX_HISTORY_TURNS * 2):]

    # 快速路徑：沒有先前的 AI 回應 → 必須檢索
    if not any(isinstance(m, AIMessage) for m in recent):
        return {
            "need_retrieval": True,
            "matched_forms": matched_forms,
            "form_explicit": False,
        }

    # 組裝對話歷史供 LLM 判斷
    history_lines: list[str] = []
    for msg in recent:
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
            history_lines.append(f"使用者：{msg.content}")
        elif isinstance(msg, AIMessage) and isinstance(msg.content, str):
            history_lines.append(f"AI 助理：{msg.content[:400]}")

    history_text = "\n".join(history_lines)

    llm = ChatOpenAI(
        model=settings.grader_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )
    result = await llm.ainvoke([
        SystemMessage(content=_ROUTER_SYSTEM),
        HumanMessage(content=f"對話歷史：\n{history_text}\n\n當前問題：{query}"),
    ])

    need_retrieval = "NO" not in result.content.strip().upper()
    return {
        "need_retrieval": need_retrieval,
        "matched_forms": matched_forms,
        "form_explicit": False,
    }

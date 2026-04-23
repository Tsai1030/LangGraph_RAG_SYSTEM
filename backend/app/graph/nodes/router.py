"""
router.py — 檢索路由節點

retrieval_router：判斷當前問題是否需要從知識庫進行新的文件檢索。
若問題屬於追問、改寫、對話延伸，可直接跳過檢索交由 responder 依對話歷史回答。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.graph.state import GraphState

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

_MAX_HISTORY_TURNS = 3  # 最多看最近 3 輪對話（6 則訊息）


async def retrieval_router(state: GraphState) -> dict:
    """
    判斷是否需要從知識庫檢索文件。
    回傳 need_retrieval: True（需要）或 False（跳過）。

    快速路徑：
    - 無對話歷史（首輪）→ 直接回傳 True，省去 LLM 呼叫
    """
    messages = state.get("messages", [])
    query = state["query"]

    # 排除當前這輪的 HumanMessage（它是 messages 的最後一則）
    prior = [m for m in messages[:-1] if isinstance(m, (HumanMessage, AIMessage))]
    recent = prior[-(_MAX_HISTORY_TURNS * 2):]  # 最近 N 輪 = 2N 則訊息

    # 快速路徑：沒有先前的 AI 回應 → 必須檢索
    if not any(isinstance(m, AIMessage) for m in recent):
        return {"need_retrieval": True}

    # 組裝對話歷史供 LLM 判斷
    history_lines: list[str] = []
    for msg in recent:
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
            history_lines.append(f"使用者：{msg.content}")
        elif isinstance(msg, AIMessage) and isinstance(msg.content, str):
            # 截斷長回應，避免超出 token
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

    # 若回應不明確，預設 YES（安全側）
    need_retrieval = "NO" not in result.content.strip().upper()
    return {"need_retrieval": need_retrieval}

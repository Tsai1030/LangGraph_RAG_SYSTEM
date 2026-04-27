"""
intent.py — 使用者意圖分類節點

判斷使用者意圖：
- 'qa'：一般知識問答
- 'form_request'：需要生成結構化表單

策略：
1. 先以關鍵字規則快速判斷（無需 LLM，效能佳）
2. 關鍵字無法確定時，交由 LLM 判斷
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.graph.state import GraphState

# 表單請求關鍵字（涵蓋繁體中文常見用法）
_FORM_KEYWORDS = [
    "表單", "檢核表", "清單", "生成表", "下載", "填寫",
    "報表", "報告書", "格式", "列表", "產生表", "製作表",
    "excel", "csv", "輸出表", "匯出", "制式", "樣板",
    "表格", "一覽表", "記錄表", "申請表", "登記表", "簽到表",
    "制表", "整理成表", "建立表", "幫我做表", "幫我整理",
    "幫我列出", "幫我生成", "幫我產生", "幫我建立",
]

_INTENT_SYSTEM_PROMPT = """\
判斷使用者問題的意圖，只輸出一個詞，不要其他文字：
- 若使用者想要「生成、製作、下載、匯出」任何形式的表格、清單、檢核表、報表 → 輸出：form_request
- 若使用者請求整理資料成表格格式，或要求可下載的結構化資料 → 輸出：form_request
- 若使用者只是詢問知識、流程、規定、說明、步驟 → 輸出：qa
- 遇到模糊情況，優先判斷為 form_request"""


async def intent_classifier(state: GraphState) -> dict:
    """
    分類使用者意圖。
    - 靜態表單明確請求（router 已設 form_explicit=True）→ 直接回 form_request，無需 LLM
    - 否則先用關鍵字規則，無法確定再呼叫 LLM
    """
    query = state["query"]
    query_lower = query.lower()

    # 靜態表單快速路徑（router 已做 form_lookup + explicit 判斷）
    if state.get("form_explicit") and state.get("matched_forms"):
        return {"intent": "form_request", "form_type": None}

    # 快速關鍵字判斷
    if any(kw in query_lower for kw in _FORM_KEYWORDS):
        return {"intent": "form_request", "form_type": None}

    # LLM 判斷（語意複雜的情況）— 用 grader_model 加速
    llm = ChatOpenAI(
        model=settings.grader_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    result = await llm.ainvoke([
        SystemMessage(content=_INTENT_SYSTEM_PROMPT),
        HumanMessage(content=query),
    ])

    intent_text = result.content.strip().lower()
    intent = "form_request" if "form_request" in intent_text else "qa"

    return {"intent": intent, "form_type": None}

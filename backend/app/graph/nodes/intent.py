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
]

_INTENT_SYSTEM_PROMPT = """\
判斷使用者問題的意圖，只輸出一個詞，不要其他文字：
- 若使用者想要生成、下載可填寫的結構化表格、檢核表、報表 → 輸出：form_request
- 若使用者只是詢問知識、流程、規定、步驟 → 輸出：qa"""


async def intent_classifier(state: GraphState) -> dict:
    """
    分類使用者意圖。
    先用關鍵字規則，無法確定再呼叫 LLM。
    """
    query = state["query"]
    query_lower = query.lower()

    # 快速關鍵字判斷
    if any(kw in query_lower for kw in _FORM_KEYWORDS):
        return {"intent": "form_request", "form_type": None}

    # LLM 判斷（語意複雜的情況）
    llm = ChatOpenAI(
        model=settings.llm_model,
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

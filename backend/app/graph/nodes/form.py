"""
form.py — 表單結構化節點

根據 context 與 query，呼叫 LLM 輸出嚴格 JSON 格式的結構化表單。
form_structurer 在 responder 之前執行，讓 responder 可在文字中提及表單內容。
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.graph.state import GraphState

_FORM_SYSTEM_PROMPT = """\
你是一位專業的營造業文件專家。
根據使用者需求與參考文件，輸出一個結構化 JSON 表單。

輸出規則：
1. 只輸出 JSON，不要加任何說明文字或 markdown 格式（不要用 ```json）
2. 嚴格遵守以下格式

{
  "form_type": "checklist",
  "title": "表單標題",
  "subtitle": "副標題（可省略，省略時不要輸出此欄位）",
  "columns": ["欄位1", "欄位2", "欄位3"],
  "rows": [
    {"欄位1": "內容", "欄位2": "內容", "欄位3": "內容"},
    ...
  ],
  "notes": "備註（可省略，省略時不要輸出此欄位）"
}

form_type 選項：
- checklist：作業檢核表（最常見）
- report：報告書
- plan：計畫書
- table：一般資料表格"""


def _parse_form_json(content: str) -> dict | None:
    """從 LLM 輸出中解析 JSON，支援多種格式"""
    content = content.strip()

    # 方法 1：直接解析（LLM 遵守純 JSON 輸出）
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 方法 2：從 markdown code block 提取
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # 方法 3：找最外層 JSON 物件
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None


async def form_structurer(state: GraphState) -> dict:
    """
    根據 context 和 query 生成結構化表單 JSON。
    非同步節點。
    """
    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    user_content = (
        f"使用者需求：{state['query']}\n\n"
        f"參考文件：\n{state.get('context', '')}"
    )

    result = await llm.ainvoke([
        SystemMessage(content=_FORM_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ])

    form_data = _parse_form_json(result.content)

    return {"form_data": form_data}

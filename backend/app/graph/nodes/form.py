"""
form.py — 表單結構化節點

使用 OpenAI Function Calling（with_structured_output）生成結構化表單。

rows 設計為 list[str]（每列用 | 分隔各欄位值），避免 list[dict[str,str]] 在
Function Calling JSON schema 中產生 additionalProperties，導致模型略過此欄位。
Python 側再將字串列轉換為 list[dict[str, str]] 供前端使用。
"""

from __future__ import annotations

from typing import Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.state import GraphState

_FORM_CONTEXT_LIMIT = 3000

_FORM_SYSTEM_PROMPT = """\
你是一位專業的營造業文件專家。
根據使用者需求與參考文件，生成一份結構化表單。

form_type 選用原則：
- checklist：作業檢核表（最常見，逐項勾核用途）
- report：報告書（填寫數據、記錄結果）
- plan：計畫書（規劃步驟、時程安排）
- table：一般資料表格（彙整資訊）

rows 格式說明：
- 每列為一個字串，各欄位值依 columns 順序以 | 分隔
- 例如 columns=["項目", "說明", "狀態"]，則某列為 "安全帽佩戴|施工中必須佩戴|□"
- 每列的欄位數量必須與 columns 數量相同"""


class FormSchema(BaseModel):
    form_type: Literal["checklist", "report", "plan", "table"] = Field(
        description="表單類型"
    )
    title: str = Field(description="表單標題")
    subtitle: Optional[str] = Field(default=None, description="副標題（可選）")
    columns: list[str] = Field(description="欄位名稱列表，至少 2 個欄位")
    rows: list[str] = Field(
        description='資料列，每列為各欄位值依 columns 順序以 | 分隔的字串。欄位數須與 columns 相同。例：["安全帽佩戴|施工中必須佩戴|□", "手套佩戴|高溫作業必須佩戴|□"]'
    )
    notes: Optional[str] = Field(default=None, description="備註（可選）")


def _rows_to_dicts(columns: list[str], raw_rows: list[str]) -> list[dict[str, str]]:
    """將 pipe-separated 字串列轉換為 list[dict[str, str]]。"""
    result = []
    for row_str in raw_rows:
        values = [v.strip() for v in row_str.split("|")]
        # 補齊或截斷至 columns 長度
        values += [""] * max(0, len(columns) - len(values))
        result.append(dict(zip(columns, values[: len(columns)])))
    return result


async def form_structurer(state: GraphState) -> dict:
    """
    根據 context 和 query 生成結構化表單。
    rows 以 pipe-separated 字串回傳，Python 側轉換為 dict 格式。
    """
    llm = ChatOpenAI(
        model=settings.form_model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).with_structured_output(FormSchema, method="function_calling")

    context = state.get("context", "")
    user_content = (
        f"使用者需求：{state['query']}\n\n"
        f"參考文件：\n{context[:_FORM_CONTEXT_LIMIT]}"
    )

    try:
        result: FormSchema = await llm.ainvoke([
            SystemMessage(content=_FORM_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ])

        form_dict = result.model_dump(exclude_none=True)
        # 將 pipe-separated rows 轉換為前端期望的 list[dict[str, str]]
        form_dict["rows"] = _rows_to_dicts(result.columns, result.rows)

        return {"form_data": form_dict}
    except Exception:
        return {"form_data": None}

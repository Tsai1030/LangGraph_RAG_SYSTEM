"""
compact.py — Token 計算與對話壓縮節點

節點：
- compact_check（同步）：計算目前訊息 token 數，判斷是否超過閾值
- summarizer（非同步）：壓縮舊訊息成摘要，保留最近 4 輪（8 則）對話
"""

from __future__ import annotations

import logging

import tiktoken
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
)
from app.config import settings
from app.core.llm import get_llm
from app.graph.state import GraphState
from app.prompts import get_prompt

logger = logging.getLogger("app.compact")

# compact 觸發閾值（tokens）
COMPACT_THRESHOLD = 8000

# 保留最近幾則訊息（4 輪對話 = 8 則）
KEEP_RECENT = 8


def _count_tokens(messages: list[BaseMessage]) -> int:
    """使用 tiktoken 計算 messages 的總 token 數（cl100k_base encoding）"""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        enc = tiktoken.get_encoding("gpt2")

    total = 0
    for msg in messages:
        if isinstance(msg.content, str):
            total += len(enc.encode(msg.content))
        elif isinstance(msg.content, list):
            for part in msg.content:
                if isinstance(part, dict) and "text" in part:
                    total += len(enc.encode(part["text"]))
    return total


def compact_check(state: GraphState) -> dict:
    """
    計算目前訊息的 token 數，判斷是否需要壓縮。
    同步節點，不呼叫 LLM。
    """
    messages = state.get("messages", [])
    token_count = _count_tokens(messages)
    return {
        "token_count": token_count,
        "is_compact_needed": token_count > COMPACT_THRESHOLD,
    }


async def summarizer(state: GraphState) -> dict:
    """
    將舊訊息壓縮成摘要，保留最近 KEEP_RECENT 則訊息。
    非同步節點。

    壓縮策略：
    1. 取出除最近 KEEP_RECENT 則以外的所有訊息（HumanMessage + AIMessage）
    2. 呼叫 LLM 生成摘要
    3. 用 RemoveMessage 從 state 中刪除舊訊息
    4. 將摘要儲存至 SQLite（conversation_summaries 表）
    """
    messages = state.get("messages", [])

    if len(messages) <= KEEP_RECENT:
        # 訊息不足，不需壓縮
        return {"is_compact_needed": False}

    old_messages = messages[:-KEEP_RECENT]

    # 組裝要摘要的對話文字
    history_lines = []
    for msg in old_messages:
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
            history_lines.append(f"使用者：{msg.content}")
        elif isinstance(msg, AIMessage) and isinstance(msg.content, str):
            history_lines.append(f"AI 助理：{msg.content}")

    if not history_lines:
        return {"is_compact_needed": False}

    history_text = "\n".join(history_lines)

    llm = get_llm("default", temperature=0)
    summary_response = await llm.ainvoke([
        HumanMessage(content=get_prompt("compact").format(history=history_text))
    ])
    # .text 是跨 provider 統一文字 accessor（Gemini 3.x 的 list[block] 也能正確抽出）
    summary_text: str = getattr(summary_response, "text", None) or (
        summary_response.content if isinstance(summary_response.content, str) else ""
    )

    # 用 RemoveMessage 刪除舊訊息（add_messages reducer 支援）
    remove_ops = [
        RemoveMessage(id=msg.id)
        for msg in old_messages
        if getattr(msg, "id", None)
    ]

    # 非同步儲存摘要至 SQLite（非關鍵，失敗不影響主流程）
    conversation_id = state.get("conversation_id", "")
    if conversation_id:
        try:
            from app.database import AsyncSessionLocal
            from app.services.conversation_service import upsert_summary

            async with AsyncSessionLocal() as db:
                await upsert_summary(
                    db=db,
                    conversation_id=conversation_id,
                    summary_text=summary_text,
                    up_to_message_id="",          # 無精確 DB message ID
                    summarized_message_count=len(old_messages),
                )
        except Exception:
            # 非致命：摘要仍在 state 內供本輪使用，但重啟後 DB 撈不到舊摘要
            logger.warning(
                "[summarizer] 摘要寫入 DB 失敗 conv=%s", conversation_id, exc_info=True,
            )

    return {
        "messages": remove_ops,        # add_messages reducer 處理刪除
        "summary": summary_text,
        "is_compact_needed": False,
    }

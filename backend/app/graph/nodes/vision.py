"""
vision.py — vision_intake 節點（VLM 圖片輸入）

放在 graph 最前面（START → vision_intake → compact_check）：
- 本輪無圖（image_refs 空）→ return {}（no-op，純文字流程逐位元不變）。
- 本輪有圖 → 用 get_llm("default")（Gemini，多模態）讀圖，產出文字解析，
  併入 state["query"]、另存 state["image_understanding"]，讓後續既有節點
  （unified_intent / retriever / grader）照常處理「文字」，邏輯零改動。

圖片從磁碟現讀，base64 只活在本 node 的 LLM call 裡，不寫回 state/checkpoint。
多模態訊息格式 = Stage 0 已驗證的 image_url data-url（格式 A）。
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import get_llm
from app.graph.state import GraphState
from app.services.image_store import to_image_block

logger = logging.getLogger("app.vision")

_SYSTEM = (
    "你是影像理解助手。請只『描述 / OCR』使用者上傳的圖片內容："
    "把標題、表格欄位與數值（逐列）、流程圖節點、關鍵中文文字、手寫/印章資訊"
    "盡量完整列出。只做客觀描述與 OCR，不要回答問題、不要評論、不要臆測。"
)


async def vision_intake(state: GraphState) -> dict:
    """有圖才跑：Gemini 讀圖 → 解析併入 query。無圖回 {}（no-op）。"""
    refs = state.get("image_refs") or []
    if not refs:
        return {}

    blocks = [b for ref in refs if (b := to_image_block(ref)) is not None]
    if not blocks:
        return {}

    query = state.get("query") or ""
    user_text = f"請描述並 OCR 這 {len(blocks)} 張圖片的內容。使用者的問題：{query or '（未附文字）'}"
    content = [{"type": "text", "text": user_text}, *blocks]

    try:
        llm = get_llm("default", temperature=0)
        resp = await llm.ainvoke([
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=content),
        ])
    except Exception as e:
        # 視覺理解失敗不應讓整輪對話崩潰 → 退化成純文字流程
        logger.exception("[vision_intake] LLM 讀圖失敗，退化為純文字: %s", e)
        return {}

    # .text 是 LangChain 跨 provider 的統一文字 accessor（Gemini 3.x 回 list[block] 也能取乾淨字串）
    understanding = getattr(resp, "text", None) or (
        resp.content if isinstance(resp.content, str) else ""
    )
    if not understanding.strip():
        return {}

    enriched = f"{query}\n\n[使用者上傳圖片的內容解析]\n{understanding}".strip()
    logger.info(
        "[vision_intake] %d 張圖，解析 %d 字，已併入 query", len(blocks), len(understanding)
    )
    return {"image_understanding": understanding, "query": enriched}

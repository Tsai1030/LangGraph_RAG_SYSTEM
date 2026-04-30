"""
source_filter.py — 來源過濾節點

在 responder 生成回答後，使用 LLM 評估哪些 retrieved chunks
實際上對回答有貢獻，以結構化輸出覆寫 sources。

僅保留 used=True 且 confidence >= CONFIDENCE_THRESHOLD 的 chunks。
"""

from __future__ import annotations

import logging
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.state import GraphState
from app.rag.retriever import format_sources

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.6


class ChunkEvaluation(BaseModel):
    chunk_index: int = Field(description="chunk 在列表中的索引（從 0 開始）")
    used: bool = Field(description="此 chunk 是否對回答有實質貢獻")
    reason: str = Field(description="一句話說明判斷依據")
    confidence: float = Field(ge=0.0, le=1.0, description="判斷信心度（0.0–1.0）")


class SourceFilterOutput(BaseModel):
    evaluations: List[ChunkEvaluation]


_SYSTEM_PROMPT = """\
你是一位來源評估助理。你的任務是判斷每個文件片段（chunk）是否對以下回答有實質貢獻。

判斷標準：
- used=true：chunk 提供了回答中使用到的資訊、數字、定義、流程或背景知識
- used=false：chunk 與回答內容無關，或主題相關但未被實際採用
- confidence：判斷信心度（0.0–1.0），語意明確則高，模稜兩可則低

注意：回答是用自然語言重述的，不會直接引用原文，請從語意層面判斷貢獻。
每個 chunk 都必須給出評估，不可略過。"""


async def source_filter(state: GraphState) -> dict:
    """
    評估 retrieved_chunks 對最終回答的實際貢獻，
    過濾後覆寫 sources（used=True 且 confidence >= 0.6 才保留）。
    若無 chunks 或無 response（靜態表單路徑）則直接回傳空 sources。
    """
    chunks = state.get("retrieved_chunks", [])
    response = state.get("response", "")

    if not chunks or not response:
        return {"sources": []}

    chunk_previews: list[str] = []
    for i, chunk in enumerate(chunks):
        meta = chunk.get("metadata", {})
        source = meta.get("source_file", "")
        h2 = meta.get("parent_h2", "")
        content = chunk.get("document", "")[:300]
        header = f"[chunk {i}]"
        if source:
            header += f" 【{source}】"
        if h2:
            header += f"【{h2}】"
        chunk_previews.append(f"{header}\n{content}")

    chunks_text = "\n\n".join(chunk_previews)

    llm = ChatOpenAI(
        model=settings.grader_model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).with_structured_output(SourceFilterOutput)

    result: SourceFilterOutput = await llm.ainvoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=f"【回答】\n{response}\n\n【文件片段】\n{chunks_text}"),
    ])

    used_indices = {
        ev.chunk_index
        for ev in result.evaluations
        if ev.used and ev.confidence >= _CONFIDENCE_THRESHOLD
    }

    filtered_chunks = [
        chunks[i] for i in sorted(used_indices) if i < len(chunks)
    ]

    logger.info(
        "[source_filter] total=%d  filtered=%d  threshold=%.1f",
        len(chunks),
        len(filtered_chunks),
        _CONFIDENCE_THRESHOLD,
    )
    for ev in result.evaluations:
        logger.debug(
            "[source_filter] chunk=%d  used=%s  conf=%.2f  reason='%s'",
            ev.chunk_index,
            ev.used,
            ev.confidence,
            ev.reason,
        )

    return {"sources": format_sources(filtered_chunks)}

"""
source_filter.py — 來源過濾節點

與 responder 並行執行。使用 query + retrieved_chunks 評估哪些 chunk
對回答問題有實質貢獻，輸出最小化（只回傳相關 chunk 索引列表）。
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


class SourceFilterOutput(BaseModel):
    relevant_indices: List[int] = Field(
        description="對回答問題有實質貢獻的 chunk 索引（從 0 開始）"
    )


_SYSTEM_PROMPT = """\
你是來源評估助理。根據問題與文件片段，列出真正能回答此問題的 chunk 索引。
只列出有實質貢獻的索引，不相關的不要列入。"""


async def source_filter(state: GraphState) -> dict:
    """
    評估 retrieved_chunks 對問題的相關性，過濾後更新 sources。
    使用 query 而非 response，可與 responder 並行執行。
    若無 chunks 則直接回傳空 sources。
    """
    chunks = state.get("retrieved_chunks", [])
    query = state.get("retrieval_query") or state.get("query", "")

    if not chunks or not query:
        return {"sources": []}

    chunk_previews: list[str] = []
    for i, chunk in enumerate(chunks):
        meta = chunk.get("metadata", {})
        source = meta.get("source_file", "")
        h2 = meta.get("parent_h2", "")
        content = chunk.get("document", "")[:120]
        header = f"[{i}]"
        if source:
            header += f"【{source}】"
        if h2:
            header += f"【{h2}】"
        chunk_previews.append(f"{header} {content}")

    chunks_text = "\n".join(chunk_previews)

    llm = ChatOpenAI(
        model=settings.grader_model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).with_structured_output(SourceFilterOutput)

    result: SourceFilterOutput = await llm.ainvoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=f"問題：{query}\n\n文件片段：\n{chunks_text}"),
    ])

    used_indices = {i for i in result.relevant_indices if 0 <= i < len(chunks)}
    filtered_chunks = [chunks[i] for i in sorted(used_indices)]

    logger.info(
        "[source_filter] total=%d  filtered=%d",
        len(chunks),
        len(filtered_chunks),
    )

    return {"sources": format_sources(filtered_chunks)}

"""
測試 retrieval_router 的路由判斷邏輯。

執行方式（在 backend/ 目錄下）：
    pytest tests/test_retrieval_router.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes.router import retrieval_router


def _make_state(query: str, history: list = None) -> dict:
    """建立測試用的 GraphState dict。"""
    messages = list(history or []) + [HumanMessage(content=query)]
    return {
        "query": query,
        "messages": messages,
    }


def _history(pairs: list[tuple[str, str]]) -> list:
    """將 (user, ai) 對話對轉成 message list。"""
    msgs = []
    for user_msg, ai_msg in pairs:
        msgs.append(HumanMessage(content=user_msg))
        msgs.append(AIMessage(content=ai_msg))
    return msgs


# ── 快速路徑（首輪，不呼叫 LLM）──────────────────────────────

@pytest.mark.asyncio
async def test_first_turn_always_retrieves():
    """首輪對話（無 AI 回應歷史）應直接回傳 need_retrieval=True，不呼叫 LLM。"""
    state = _make_state("安全帽的佩戴規範是什麼？")

    with patch("app.graph.nodes.router.ChatOpenAI") as mock_llm_cls:
        result = await retrieval_router(state)

    assert result["need_retrieval"] is True
    mock_llm_cls.assert_not_called()  # 不應呼叫 LLM


# ── LLM 判斷路徑 ────────────────────────────────────────────

def _mock_llm(answer: str):
    """回傳一個模擬 LLM，ainvoke 固定回傳指定字串。"""
    mock_resp = MagicMock()
    mock_resp.content = answer
    mock_instance = MagicMock()
    mock_instance.ainvoke = AsyncMock(return_value=mock_resp)
    mock_cls = MagicMock(return_value=mock_instance)
    return mock_cls


@pytest.mark.asyncio
async def test_followup_rephrase_skips_retrieval():
    """「能說得更清楚嗎？」類的改寫請求應跳過檢索。"""
    history = _history([("安全帽的佩戴規範是什麼？", "安全帽須全程佩戴...")])
    state = _make_state("能說得更清楚嗎？", history)

    with patch("app.graph.nodes.router.ChatOpenAI", _mock_llm("NO")):
        result = await retrieval_router(state)

    assert result["need_retrieval"] is False


@pytest.mark.asyncio
async def test_new_topic_requires_retrieval():
    """問新主題應需要檢索。"""
    history = _history([("安全帽規範？", "須全程佩戴。")])
    state = _make_state("鷹架搭設的安全距離是多少？", history)

    with patch("app.graph.nodes.router.ChatOpenAI", _mock_llm("YES")):
        result = await retrieval_router(state)

    assert result["need_retrieval"] is True


@pytest.mark.asyncio
async def test_form_request_requires_retrieval():
    """表單生成請求應需要檢索（即使看起來像追問）。"""
    history = _history([("安全規範有哪些？", "包含安全帽、手套...")])
    state = _make_state("幫我做一個安全規範的檢核表", history)

    with patch("app.graph.nodes.router.ChatOpenAI", _mock_llm("YES")):
        result = await retrieval_router(state)

    assert result["need_retrieval"] is True


@pytest.mark.asyncio
async def test_ambiguous_defaults_to_retrieval():
    """LLM 回應不含 NO 時，預設需要檢索（安全側）。"""
    history = _history([("問題A？", "回答A。")])
    state = _make_state("那第一點呢？", history)

    with patch("app.graph.nodes.router.ChatOpenAI", _mock_llm("MAYBE")):  # 不明確
        result = await retrieval_router(state)

    assert result["need_retrieval"] is True

"""
測試 unified_intent node 與其純函式 helpers。

測試策略：
- 純函式（_resolve_candidates / _normalize_decision / _build_state_update）直接以參數驗證行為
- LLM 路徑全部 mock；驗證「LLM 給什麼 → state 變什麼」與規範化規則
- 冷啟動 fast-path 不打 LLM（mock 不應被呼叫）

不在這裡測 LLM 自身判斷準確度——那是 prompt eval（跑 scripts/eval_intent.py 真打 API）。

執行：
    cd backend && uv run pytest tests/test_unified_intent.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes.unified_intent import (
    IntentDecision,
    _build_state_update,
    _normalize_decision,
    _resolve_candidates,
    _resolve_form_meta,
    unified_intent,
)


# ──────────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────────

def _history(*pairs: tuple[str, str]) -> list:
    """[(user_msg, ai_msg), ...] → message list（user/ai/user/ai... 順序）"""
    msgs = []
    for u, a in pairs:
        msgs.append(HumanMessage(content=u))
        msgs.append(AIMessage(content=a))
    return msgs


def _state(query: str, **overrides) -> dict:
    """建立測試用 state，messages 含當前 user 訊息（測試可用 messages= 覆寫加上歷史）"""
    state: dict = {
        "query": query,
        "messages": [HumanMessage(content=query)],
        "form_fill_session": None,
        "prev_form_data": None,
    }
    state.update(overrides)
    return state


def _decision(
    intent: str,
    target_form_id: str | None = None,
    retrieval_topic: str | None = None,
    need_retrieval: bool = False,
    reason: str = "test",
) -> IntentDecision:
    return IntentDecision(
        intent=intent,
        target_form_id=target_form_id,
        retrieval_topic=retrieval_topic,
        need_retrieval=need_retrieval,
        reason=reason,
    )


def _patch_llm(decision: IntentDecision):
    """patch ChatOpenAI 讓 with_structured_output(...).ainvoke() 固定回傳 decision。"""
    inner = MagicMock()
    inner.ainvoke = AsyncMock(return_value=decision)

    chain = MagicMock()
    chain.with_structured_output.return_value = inner

    cls = MagicMock(return_value=chain)
    return patch("app.graph.nodes.unified_intent.ChatOpenAI", cls), cls


# ──────────────────────────────────────────────────────────────────
# _resolve_candidates — 候選召回（含歷史 fallback）
# ──────────────────────────────────────────────────────────────────

class TestResolveCandidates:
    def test_query_hit_skips_history(self):
        """當前 query 命中時不該再看歷史"""
        cs = _resolve_candidates(
            "我要填工務所辦公室設置作業檢核表",
            _history(("我要動員開工檢核表", "已生成《動員開工作業檢核表》")),
        )
        assert [c["form_id"] for c in cs] == ["010102"]

    def test_falls_back_to_history(self):
        """query 命不中時拼接歷史再比對"""
        cs = _resolve_candidates(
            "我想要填入資訊",
            _history(("我要動員檢核表", "請點擊下方下載")),
        )
        assert [c["form_id"] for c in cs] == ["010101"]

    def test_empty_when_neither_match(self):
        cs = _resolve_candidates(
            "今天天氣如何",
            _history(("你好", "您好，有什麼可以協助")),
        )
        assert cs == []

    def test_empty_history_returns_empty(self):
        cs = _resolve_candidates("不認得的 query", [])
        assert cs == []


# ──────────────────────────────────────────────────────────────────
# _resolve_form_meta — id → metadata 轉換
# ──────────────────────────────────────────────────────────────────

class TestResolveFormMeta:
    def test_uses_candidates_first(self):
        cands = [{"form_id": "010101", "display_name": "FROM_CAND", "download_url": "/x"}]
        meta = _resolve_form_meta("010101", cands)
        assert meta["display_name"] == "FROM_CAND"

    def test_falls_back_to_registry(self):
        # 010102 不在 candidates，會從 registry 撈
        meta = _resolve_form_meta("010102", [])
        assert meta["form_id"] == "010102"
        assert "工務所" in meta["display_name"]

    def test_unknown_id_returns_placeholder(self):
        meta = _resolve_form_meta("999999", [])
        assert meta == {"form_id": "999999", "display_name": "999999", "download_url": ""}


# ──────────────────────────────────────────────────────────────────
# _normalize_decision — 規範化規則
# ──────────────────────────────────────────────────────────────────

class TestNormalizeDecision:
    def test_invalid_target_id_falls_back_to_qa(self):
        """LLM 給不在候選清單的 target_form_id → 退回 qa"""
        intent, tid = _normalize_decision(
            _decision("static_form_download", target_form_id="999999"),
            candidates=[{"form_id": "010101", "display_name": "X", "download_url": "/x"}],
            fill_session={},
            prev_form_data=None,
        )
        assert intent == "qa"
        assert tid is None

    def test_static_fill_with_valid_target_passes(self):
        intent, tid = _normalize_decision(
            _decision("static_form_fill", target_form_id="010101"),
            candidates=[{"form_id": "010101", "display_name": "X", "download_url": "/x"}],
            fill_session={},
            prev_form_data=None,
        )
        assert intent == "static_form_fill"
        assert tid == "010101"

    def test_session_target_used_when_llm_unfilled(self):
        """active session 但 LLM 沒給 target → 沿用 session id"""
        intent, tid = _normalize_decision(
            _decision("static_form_fill", target_form_id=None),
            candidates=[],
            fill_session={"target_form_id": "010101", "status": "collecting"},
            prev_form_data=None,
        )
        assert intent == "static_form_fill"
        assert tid == "010101"

    def test_completed_session_target_also_valid(self):
        """completed session 的 id 也算合法 target（讓編輯流程能走）"""
        intent, tid = _normalize_decision(
            _decision("static_form_fill", target_form_id="010101"),
            candidates=[],
            fill_session={"target_form_id": "010101", "status": "completed"},
            prev_form_data=None,
        )
        assert intent == "static_form_fill"
        assert tid == "010101"

    def test_form_continuation_without_topic_demoted(self):
        """form_continuation 但缺 retrieval_topic → 改 dynamic_form_generate"""
        intent, _ = _normalize_decision(
            _decision("form_continuation", retrieval_topic=None),
            candidates=[],
            fill_session={},
            prev_form_data={"title": "X"},
        )
        assert intent == "dynamic_form_generate"

    def test_form_continuation_without_prev_form_demoted(self):
        intent, _ = _normalize_decision(
            _decision("form_continuation", retrieval_topic="某主題"),
            candidates=[],
            fill_session={},
            prev_form_data=None,
        )
        assert intent == "dynamic_form_generate"

    def test_qa_target_id_cleared(self):
        """qa intent 不應帶 target_form_id"""
        intent, tid = _normalize_decision(
            _decision("qa", target_form_id=None),
            candidates=[{"form_id": "010101", "display_name": "X", "download_url": "/x"}],
            fill_session={},
            prev_form_data=None,
        )
        assert intent == "qa"
        assert tid is None


# ──────────────────────────────────────────────────────────────────
# _build_state_update — state shape per intent
# ──────────────────────────────────────────────────────────────────

class TestBuildStateUpdate:
    _META = {"form_id": "010101", "display_name": "動員開工作業檢核表", "download_url": "/x"}

    def test_static_form_download(self):
        st = _build_state_update(
            "static_form_download", "010101",
            _decision("static_form_download", need_retrieval=False),
            [self._META],
        )
        assert st["intent"] == "static_form_download"
        assert st["form_explicit"] is True
        assert st["need_retrieval"] is False
        assert st["matched_forms"][0]["form_id"] == "010101"

    def test_static_form_fill(self):
        st = _build_state_update(
            "static_form_fill", "010101",
            _decision("static_form_fill"),
            [self._META],
        )
        assert st["intent"] == "static_form_fill"
        assert st["form_explicit"] is True
        assert st["matched_forms"][0]["form_id"] == "010101"

    def test_qa_keeps_candidates_for_download_hint(self):
        """qa 把候選帶下去，讓 responder 在回答末段加下載提示"""
        st = _build_state_update(
            "qa", None,
            _decision("qa", need_retrieval=True),
            [self._META],
        )
        assert st["intent"] == "qa"
        assert st["form_explicit"] is False
        assert any(c["form_id"] == "010101" for c in st["matched_forms"])

    def test_dynamic_form_generate(self):
        st = _build_state_update(
            "dynamic_form_generate", None,
            _decision("dynamic_form_generate"),
            [],
        )
        assert st["intent"] == "dynamic_form_generate"
        assert st["need_retrieval"] is True
        assert st["matched_forms"] == []

    def test_form_continuation_sets_retrieval_query(self):
        st = _build_state_update(
            "form_continuation", None,
            _decision("form_continuation", retrieval_topic="動員開工"),
            [],
        )
        assert st["intent"] == "form_continuation"
        assert st["is_form_continuation"] is True
        assert st["retrieval_query"] == "動員開工"


# ──────────────────────────────────────────────────────────────────
# unified_intent — 主入口（含 cold-start 與 LLM-mocked 整合）
# ──────────────────────────────────────────────────────────────────

class TestUnifiedIntentColdStart:
    @pytest.mark.asyncio
    async def test_cold_start_returns_qa_without_llm(self):
        """首輪 + 無候選 + 無前輪表單 + 無 session → qa，且不應建立 LLM"""
        state = _state("第一個問題")
        with patch("app.graph.nodes.unified_intent.ChatOpenAI") as mock_llm:
            result = await unified_intent(state)

        assert result["intent"] == "qa"
        assert result["need_retrieval"] is True
        assert result["matched_forms"] == []
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_active_session_skips_cold_start(self):
        """有 active session 即使首輪也要走 LLM（不能 fast-return qa）"""
        decision = _decision("static_form_fill", target_form_id="010101")
        state = _state("OK")
        state["form_fill_session"] = {"target_form_id": "010101", "status": "collecting", "collected": {}}

        ctx, mock_llm = _patch_llm(decision)
        with ctx:
            result = await unified_intent(state)

        assert result["intent"] == "static_form_fill"
        mock_llm.assert_called_once()


class TestUnifiedIntentLLMPath:
    @pytest.mark.asyncio
    async def test_llm_static_form_fill_routes_correctly(self):
        decision = _decision("static_form_fill", target_form_id="010101")
        state = _state(
            "我要填動員開工檢核表",
            messages=_history(("第一輪", "回答")) + [HumanMessage(content="我要填動員開工檢核表")],
        )

        ctx, _ = _patch_llm(decision)
        with ctx:
            result = await unified_intent(state)

        assert result["intent"] == "static_form_fill"
        assert result["form_explicit"] is True
        assert result["matched_forms"][0]["form_id"] == "010101"

    @pytest.mark.asyncio
    async def test_llm_qa_with_candidates_keeps_them(self):
        """qa 路徑仍把候選帶下去用於下載提示"""
        decision = _decision("qa", need_retrieval=True)
        state = _state(
            "動員開工要做哪些初期計畫？",
            messages=_history(("Q", "A")) + [HumanMessage(content="動員開工要做哪些初期計畫？")],
        )

        ctx, _ = _patch_llm(decision)
        with ctx:
            result = await unified_intent(state)

        assert result["intent"] == "qa"
        assert result["form_explicit"] is False
        assert any(c["form_id"] == "010101" for c in result["matched_forms"])

    @pytest.mark.asyncio
    async def test_llm_invalid_target_falls_back_to_qa(self):
        """LLM 給越界 target → 規範化退回 qa"""
        decision = _decision("static_form_download", target_form_id="999999")
        state = _state(
            "隨便聊聊",
            messages=_history(("Q", "A")) + [HumanMessage(content="隨便聊聊")],
        )

        ctx, _ = _patch_llm(decision)
        with ctx:
            result = await unified_intent(state)

        assert result["intent"] == "qa"
        assert result["form_explicit"] is False

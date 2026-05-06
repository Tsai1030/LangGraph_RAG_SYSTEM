"""
unified_intent.py — 統一意圖分類節點

設計：純 LLM 判斷 + post-normalization。每輪訊息都打一次 LLM，由 prompt 與
few-shot 把規則教給模型。

為什麼不用 keyword fast-path：
- 短訊息看字面易誤判（例「我要規範的詳細說明」含「我要」會被誤判成索取靜態檔）
- keyword 集合會無限膨脹、難維護、難測試組合
- gpt-5.4 級的模型對六分類已足夠穩定

為什麼也不用「冷啟動 → qa」fast-path：
- 首輪訊息**不一定是 qa**：可能是 dynamic_form_generate（「做一份新人是非題」）、
  static_form_download（「下載動員開工檢核表」）等
- 多打一次 LLM（≈300ms）換取每輪都正確分類，比「省一次 LLM 但首輪可能誤判」值得

回傳的 state 更新：
- intent: qa | static_form_download | static_form_fill | dynamic_form_generate
          | form_continuation | dynamic_form_export
- need_retrieval / matched_forms / form_explicit / is_form_continuation
- retrieval_query（form_continuation 時帶推斷主題詞）
- export_format（dynamic_form_export 時帶 xlsx / csv）
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.state import GraphState
from app.rag.form_lookup import get_form_meta, lookup_forms

logger = logging.getLogger(__name__)

_MAX_HISTORY_TURNS = 3
_HISTORY_MSG_CHARS = 400  # 單則訊息截斷長度（避免 prompt 爆量）


# ──────────────────────────────────────────────────────────────────
# Schema — LLM 結構化輸出
# ──────────────────────────────────────────────────────────────────

class IntentDecision(BaseModel):
    intent: Literal[
        "qa",
        "static_form_download",
        "static_form_fill",
        "dynamic_form_generate",
        "form_continuation",
        "dynamic_form_export",
    ] = Field(description="使用者意圖分類（六選一）")
    export_format: Optional[Literal["xlsx", "csv"]] = Field(
        default=None,
        description="若 intent=dynamic_form_export，指定匯出格式；其他情況為 null",
    )
    target_form_id: Optional[str] = Field(
        default=None,
        description="若 intent=static_form_*，填入候選 form_id；其他情況為 null",
    )
    retrieval_topic: Optional[str] = Field(
        default=None,
        description="若 intent=form_continuation，填入推斷的表單主題詞（10字內）；其他情況為 null",
    )
    need_retrieval: bool = Field(
        description="是否需要 RAG 檢索（static_form_* 為 false；其餘依規則）"
    )
    reason: str = Field(description="一句話判斷依據（30字內）")


_SYSTEM_PROMPT = """\
你是對話分析助理。依使用者「當前訊息」與「對話脈絡」決定處理方式，並以 JSON 結構化輸出。

【intent 六選一】
1. static_form_download — 索取既有靜態表的**空白原檔**下載
2. static_form_fill     — 把資料**填寫進**既有靜態表（agent 寫好回傳）
3. dynamic_form_generate — 產生**全新**結構化表單（沒有對應靜態表，或要客製版）
4. form_continuation     — 延續「上一輪生成過的動態表單」（再來幾組／多出幾題／改題型）
5. dynamic_form_export   — 把**上一輪已生成的動態表單**轉成 Excel 或 CSV 讓使用者下載（不重新生成內容）
6. qa                    — 詢問知識、規範、流程、解說；無表單意圖

【決策原則（依序判斷）】

1. 看訊息**整體語意**，不要被單一動詞字面騙：
   - 「我要這份規範的詳細說明」 → qa（要解說，不是要檔案）
   - 「我要動員開工檢核表」     → static_form_download（要檔案）
   - 「我要填動員開工檢核表」   → static_form_fill（要填）

2. 利用「對話歷史」理解上下文：
   - 上輪在問問題、本輪「我要再深入點」 → 仍是 qa（深度討論延續）
   - 上輪是表單下載、本輪「再給我一次」 → static_form_download
   - 上輪是填表中、本輪「已完成填寫」「就這樣」「OK」「改成 abc」 → static_form_fill（沿用 session）

3. 候選靜態表清單為空時，**禁止輸出 static_form_***（除非有 active session）。

4. form_continuation **必要條件**：補充資訊明確標示「上一輪曾生成過動態表單」，
   且訊息語意是「再多來幾筆／改題型」之類**內容延續或改寫**。retrieval_topic 必填。

5. dynamic_form_export **必要條件**：補充資訊有「上一輪曾生成過動態表單」，
   且訊息明確要把該表轉成可下載檔（「給我 excel」「下載 csv」「匯出」「轉成 xlsx」）。
   - export_format 必填（xlsx / csv）；訊息含「excel/xlsx」→ xlsx，含「csv」→ csv
   - 不指定格式時預設 xlsx
   - 與 form_continuation 區分：export 不重新生成內容，只轉檔；continuation 會改寫表

6. 模糊難判時 → 偏向 qa（保守）；need_retrieval 偏向 true（保守）。

【static_form_fill 的兩種觸發】
A. **新填**：候選非空 + 訊息語意明確要填寫該表（含「填」「填寫」「協助填」「幫我填」「我要填」）
B. **續填／編輯**：active 或 completed session 進行中，訊息為：
   - 補欄位值（如「工程名稱叫和平大樓」）
   - 結束指示（「已完成填寫」「就這樣」「OK」「改完了」）
   - 編輯指令（「把備註改成 abc」「全部填 test」）
   - 此時 target_form_id 沿用 session 的 id

【target_form_id 規則】
- static_form_* 必填，且必須是「候選清單中的 id」或「現有 session 的 id」
- 其他 intent 一律填 null

【few-shot 範例】

[A] 「我要填動員開工檢核表」 候選=[010101 動員開工作業檢核表]
    → static_form_fill / target=010101 / 「明確要填靜態表」

[B] 「下載動員開工檢核表」 候選=[010101]
    → static_form_download / target=010101 / 「明確下載」

[C] 「我要動員檢核表」 候選=[010101]，訊息**無 ?/什麼/如何/解說等 qa 訊號**
    → static_form_download / target=010101 / 「我要 + 表名 = 索取檔案」

[D] 「動員開工是什麼？」 候選=[010101]
    → qa / target=null / need_retrieval=true / 「知識問答，候選會在回答末尾以下載連結輔助」

[E] 「我要這份規範的詳細說明」 候選=[010101 從歷史推斷]，先前在 qa 串
    → qa / target=null / 「使用者要解說，不是要檔案 — 不要被「我要」字面騙」

[F] 「好我要填寫」 候選=[]，session=010101 status=collecting
    → static_form_fill / target=010101 / 「沿用 session id」

[G] 「全部都幫我填上 test 給我」 候選=[]，session=010101 status=collecting
    → static_form_fill / target=010101 / 「自動填假資料指令」

[H] 「鋼筋規範是什麼」 候選=[]，session=010101 status=collecting
    → qa / 「明確切換無關主題」

[I] 「把備註的 test 改成 123」 候選=[]，session=010101 status=completed
    → static_form_fill / target=010101 / 「重啟編輯」

[J] 「幫我做一份新的開工檢核表」 候選=[010101]
    → dynamic_form_generate / 「使用者要新版本而非靜態表」

[K] 「再來五組」 候選=[]，prev_form_data=新人訓練是非題
    → form_continuation / retrieval_topic=新人訓練是非題

[L] 「給我 excel」 候選=[]，prev_form_data=新人知識選擇題
    → dynamic_form_export / export_format=xlsx / 「明確要轉檔」

[M] 「轉成 csv 下載」 候選=[]，prev_form_data=動員開工檢核表
    → dynamic_form_export / export_format=csv

[N] 「再做一份選擇題」 候選=[]，prev_form_data=新人知識是非題
    → form_continuation（不是 export，是要重生表）

reason 用 30 字內中文說明依據。"""


# ──────────────────────────────────────────────────────────────────
# Pure helpers — 純函式，無副作用，易單元測試
# ──────────────────────────────────────────────────────────────────

def _resolve_candidates(query: str, recent_messages: list) -> list[dict]:
    """候選靜態表 = 先用本輪 query 比對；命不中時 fallback 拼接最近對話再比對一次。

    解決使用者第二輪只說「我想要填入資訊」（無表名）時，能延續上一輪提到的表單。
    """
    direct = lookup_forms(query)
    if direct:
        return direct
    if not recent_messages:
        return []
    history_text = " ".join(
        m.content[:_HISTORY_MSG_CHARS]
        for m in recent_messages
        if hasattr(m, "content") and isinstance(m.content, str)
    )
    return lookup_forms(history_text) if history_text else []


def _resolve_form_meta(form_id: str, candidates: list[dict]) -> dict:
    """取出 form_id 的 metadata。優先用本輪 candidates，再 fallback 到 registry，最後給 placeholder。"""
    for c in candidates:
        if c["form_id"] == form_id:
            return c
    meta = get_form_meta(form_id)
    return meta or {"form_id": form_id, "display_name": form_id, "download_url": ""}


def _build_history_text(recent_messages: list) -> str:
    """格式化對話歷史給 LLM。每則訊息截斷至 _HISTORY_MSG_CHARS 字以避免 prompt 爆量。"""
    lines: list[str] = []
    for msg in recent_messages:
        if not (hasattr(msg, "content") and isinstance(msg.content, str)):
            continue
        text = msg.content[:_HISTORY_MSG_CHARS]
        if isinstance(msg, HumanMessage):
            lines.append(f"使用者：{text}")
        elif isinstance(msg, AIMessage):
            lines.append(f"AI 助理：{text}")
    return "\n".join(lines) if lines else "（無）"


def _build_user_prompt(
    query: str,
    candidates: list[dict],
    prev_form_data: Optional[dict],
    fill_session: dict,
    history_text: str,
) -> str:
    """組裝給 LLM 的 user prompt。"""
    if candidates:
        cand_lines = "\n".join(
            f"- form_id={c['form_id']}  display_name={c['display_name']}"
            for c in candidates
        )
    else:
        cand_lines = "（無候選靜態表）"

    prev_form_hint = (
        f"前一輪曾生成過動態表單（標題：{prev_form_data.get('title', '未知')}）"
        if prev_form_data
        else "前一輪未生成動態表單"
    )

    status = fill_session.get("status")
    target = fill_session.get("target_form_id")
    if status == "collecting":
        fill_hint = (
            f"進行中填表 session：target_form_id={target}，"
            f"已收集 {len(fill_session.get('collected', {}))} 欄位"
        )
    elif status == "completed":
        fill_hint = f"上一份填表 session 已完成：target_form_id={target}（可重啟編輯）"
    else:
        fill_hint = "無進行中／可重啟的填表 session"

    return (
        f"對話歷史：\n{history_text}\n\n"
        f"當前訊息：{query}\n\n"
        f"候選靜態表：\n{cand_lines}\n\n"
        f"補充資訊：{prev_form_hint}\n{fill_hint}"
    )


def _normalize_decision(
    decision: IntentDecision,
    candidates: list[dict],
    fill_session: dict,
    prev_form_data: Optional[dict],
) -> tuple[str, Optional[str]]:
    """LLM 越界輸出防護。回傳 (intent, target_form_id)。

    規則：
    - static_form_* 但 target_form_id 不在候選 ∪ session id → 退回 qa
    - static_form_* 但 target 為 null 且有 active/completed session → 沿用 session id
    - form_continuation 但缺 prev_form_data 或 retrieval_topic → 改 dynamic_form_generate
    - dynamic_form_export 但缺 prev_form_data → 改 qa（沒得轉的表）
    """
    intent = decision.intent
    target_id = decision.target_form_id

    valid_ids = {c["form_id"] for c in candidates}
    session_target = fill_session.get("target_form_id")
    if session_target and fill_session.get("status") in ("collecting", "completed"):
        valid_ids.add(session_target)

    if intent in ("static_form_download", "static_form_fill"):
        if not target_id and session_target:
            target_id = session_target
        if not target_id or target_id not in valid_ids:
            intent = "qa"
            target_id = None

    if intent == "form_continuation":
        if not prev_form_data or not decision.retrieval_topic:
            intent = "dynamic_form_generate"

    if intent == "dynamic_form_export" and not prev_form_data:
        intent = "qa"

    return intent, target_id


def _build_state_update(
    intent: str,
    target_id: Optional[str],
    decision: IntentDecision,
    candidates: list[dict],
) -> dict:
    """根據規範化後的 (intent, target_id) 產生要回給 graph 的 state 變更 dict。"""
    result: dict = {
        "intent": intent,
        "need_retrieval": decision.need_retrieval,
        "form_explicit": False,
        "is_form_continuation": False,
        "matched_forms": [],
    }

    if intent == "static_form_download":
        result["matched_forms"] = [_resolve_form_meta(target_id, candidates)]
        result["form_explicit"] = True
        result["need_retrieval"] = False
    elif intent == "static_form_fill":
        result["matched_forms"] = [_resolve_form_meta(target_id, candidates)]
        result["form_explicit"] = True
        result["need_retrieval"] = False
    elif intent == "qa":
        # qa 仍把候選表帶下去，讓 responder 在回答末尾附下載連結
        result["matched_forms"] = candidates
    elif intent == "dynamic_form_generate":
        result["need_retrieval"] = True
    elif intent == "form_continuation":
        result["is_form_continuation"] = True
        result["need_retrieval"] = True
        result["retrieval_query"] = decision.retrieval_topic
    elif intent == "dynamic_form_export":
        result["need_retrieval"] = False
        result["export_format"] = decision.export_format or "xlsx"

    return result


# ──────────────────────────────────────────────────────────────────
# LLM wrapper
# ──────────────────────────────────────────────────────────────────

async def _llm_classify(
    query: str,
    candidates: list[dict],
    prev_form_data: Optional[dict],
    fill_session: dict,
    recent_messages: list,
) -> IntentDecision:
    """單次 LLM call 取得意圖判斷。"""
    history_text = _build_history_text(recent_messages)
    user_prompt = _build_user_prompt(
        query, candidates, prev_form_data, fill_session, history_text,
    )

    llm = ChatOpenAI(
        model=settings.grader_model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).with_structured_output(IntentDecision)

    return await llm.ainvoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ])


# ──────────────────────────────────────────────────────────────────
# Graph node 主入口
# ──────────────────────────────────────────────────────────────────

async def unified_intent(state: GraphState) -> dict:
    """主流程：每輪都跑 LLM 分類 → 規範化 → 組 state 變更。"""
    query = state["query"]

    messages = state.get("messages", [])
    prior = [m for m in messages[:-1] if isinstance(m, (HumanMessage, AIMessage))]
    recent = prior[-(_MAX_HISTORY_TURNS * 2):]
    prev_form_data = state.get("prev_form_data")
    fill_session = state.get("form_fill_session") or {}

    candidates = _resolve_candidates(query, recent)

    # LLM 分類（每輪都打；不再用「首輪→qa」fast-path 因為首輪可能是動態表單請求）
    decision = await _llm_classify(query, candidates, prev_form_data, fill_session, recent)

    # 規範化（防 LLM 越界）
    intent, target_id = _normalize_decision(
        decision, candidates, fill_session, prev_form_data,
    )

    logger.info(
        "[unified_intent] intent=%s target=%s need_retrieval=%s reason=%r",
        intent, target_id, decision.need_retrieval, decision.reason,
    )

    return _build_state_update(intent, target_id, decision, candidates)

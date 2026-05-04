"""
unified_intent.py — 統一意圖分類節點

一次 LLM call 完成所有路由決策，取代原本 router + intent_classifier 的雙層
keyword + LLM 判斷，避免兩組關鍵字互相誤觸發。

輸出（IntentDecision）：
- intent: qa | static_form_download | dynamic_form_generate | form_continuation
- target_form_id: 命中的靜態表 form_id（intent=static_form_download 時必填）
- retrieval_topic: 延續主題詞（intent=form_continuation 時必填）
- need_retrieval: 是否需要 RAG 檢索
- reason: 一句話判斷依據

設計重點：
- lookup_forms 只做「候選召回」，由 LLM 看 query + 候選清單 + 對話歷史決策
- 首輪（無 AI 歷史）且無候選靜態表 → 直接 qa + 需檢索，不呼叫 LLM
"""

from __future__ import annotations

from typing import Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

import logging

from app.config import settings
from app.graph.state import GraphState
from app.rag.form_lookup import get_form_meta, lookup_forms

logger = logging.getLogger(__name__)

_MAX_HISTORY_TURNS = 3

# 明確的「要填寫」動詞片語：候選非空時看到任一片語 → 直接走 static_form_fill 快速路徑
# 這不是 keyword routing 的回頭路；候選召回仍依 form_lookup，只是把「填」這個明確動詞的判斷
# 從 LLM 拿回來，避免 mini 模型在 download/fill 之間搖擺。
_FILL_TRIGGER_PHRASES = (
    "幫我填", "協助填", "請填", "要填", "想填", "來填", "需要填", "代填",
    "自動填", "幫忙填", "替我填",
    "填寫", "填入", "填好", "把資料填", "把內容填", "都填", "全填", "全部填",
)

# 明確「下載原檔」訊號（協助 fast-path 區分 download vs fill）
_DOWNLOAD_TRIGGER_PHRASES = (
    "下載", "給我空白", "原始檔", "空白檔", "範本", "檔案下載",
)

# 「編輯已完成填寫」訊號：填完表後想修改某些欄位
_EDIT_TRIGGER_PHRASES = (
    "改成", "改為", "改一下", "改這", "改那", "更新",
    "替換", "重新填", "再填", "修改", "編輯", "改掉",
)


class IntentDecision(BaseModel):
    intent: Literal[
        "qa",
        "static_form_download",
        "static_form_fill",
        "dynamic_form_generate",
        "form_continuation",
    ] = Field(description="使用者意圖分類（五選一）")
    target_form_id: Optional[str] = Field(
        default=None,
        description="若 intent=static_form_download 或 static_form_fill，填入候選 form_id；其他情況為 null",
    )
    retrieval_topic: Optional[str] = Field(
        default=None,
        description="若 intent=form_continuation，填入推斷的表單主題詞（10字內）；其他情況為 null",
    )
    need_retrieval: bool = Field(
        description="是否需要 RAG 檢索（static_form_* = false；其餘依規則決定）"
    )
    reason: str = Field(description="一句話判斷依據（20字內）")


_SYSTEM_PROMPT = """\
你是對話分析助理。為使用者的當前訊息決定處理方式，並以 JSON 結構化回傳。

【intent 五選一】
1. static_form_download
   - 使用者要索取「候選靜態表清單」中某一份檔案的**原始空白檔**下載
   - 訊號：「給我這份」「下載這份檢核表」「我要這份表單」「給我空白檔」
   - target_form_id 必填，須為候選清單中存在的 id
2. static_form_fill
   - 使用者要把資料**填寫進**既有靜態表，agent 會逐欄收集後寫入並回傳填好的檔
   - 強訊號（任一即可）：「填」「填寫」「填入」「填好」「協助填」「幫我填」「我要填」「想填」「需要填」「來填」「代填」「把資料填」「全部填」「自動填」「隨便填」
   - 或：當前已有填表 session 進行中（補充資訊會標示），使用者訊息是補欄位值或結束指示
   - target_form_id 必填，須為候選清單中存在的 id（或現有 session 的 id）
3. dynamic_form_generate
   - 使用者要產生**全新**結構化表單（清單／檢核表／報表）
   - 訊號：「幫我做一份…表」「整理成表格」「列一個…清單」「產出檢核表」
   - 與既有靜態表主題不一致、或候選清單為空
4. form_continuation
   - 延續「上一輪曾生成過的動態表單」（補資料：「再來五組」「多出幾題」「繼續做」）
   - 必要條件：補充資訊標示「上一輪有生成表單」
   - retrieval_topic 必填（從歷史推斷主題，10字內）
5. qa
   - 詢問知識、規範、流程、定義、步驟說明；無表單意圖

【need_retrieval】
- static_form_download / static_form_fill → false
- dynamic_form_generate / form_continuation → true
- qa：若是改寫前一輪回答、追問前一輪細節、致謝確認 → false；其餘 → true

【判斷原則】
- 候選靜態表清單為空且無進行中填表 session 時，禁止輸出 static_form_*
- download vs fill 的關鍵差異：download = 要空白檔，fill = 要把資料填進去
- 進行中的填表 session：使用者若是給欄位值或要結束填表 → static_form_fill；改問完全不相關的知識 → qa
- 訊息有歧義時：偏向 qa；need_retrieval 偏向 true（保守）
- target_form_id 須在候選 id 內或為現有 session id；其他 intent 一律填 null
- reason 用 20 字內中文說明判斷依據

【few-shot 範例】
[A] 訊息：「我要填動員開工檢核表」候選：[010101 動員開工作業檢核表]
  → static_form_fill, target_form_id=010101, need_retrieval=false  ★「要填」+ 候選 → fill

[B] 訊息：「下載動員開工檢核表」候選：[010101]
  → static_form_download, target_form_id=010101, need_retrieval=false

[C] 訊息：「動員開工是什麼？」候選：[010101]
  → qa, target_form_id=null（候選會在回答末尾以下載連結提示，不算 static_form_*）

[D] 訊息：「好我要填寫」候選：[]，session=010101 (collecting)
  → static_form_fill, target_form_id=010101  ★沿用 session id

[E] 訊息：「全部都幫我填上 test 給我」候選：[]，session=010101 (collecting)
  → static_form_fill, target_form_id=010101  ★「自動填假資料」也是 fill 訊號

[F] 訊息：「鋼筋規範是什麼？」候選：[]，session=010101 (collecting)
  → qa  ★明確切換無關主題

[G] 訊息：「幫我做一份新的開工檢核表」候選：[010101]
  → dynamic_form_generate（使用者要新版而非既有靜態表）"""


async def unified_intent(state: GraphState) -> dict:
    """
    一次 LLM call 完成意圖分類 + 路由決策。

    回傳的 state 更新：
    - intent: 'qa' | 'static_form_download' | 'dynamic_form_generate' | 'form_continuation'
    - need_retrieval: bool
    - matched_forms: list[dict]   （static_form_download 留命中那份；qa 留候選用於下載提示；其他清空）
    - form_explicit: bool         （intent=static_form_download 時 True）
    - is_form_continuation: bool
    - retrieval_query: Optional[str]  （form_continuation 時設為 retrieval_topic）
    """
    query = state["query"]
    candidates = lookup_forms(query)

    messages = state.get("messages", [])
    prior = [m for m in messages[:-1] if isinstance(m, (HumanMessage, AIMessage))]
    recent = prior[-(_MAX_HISTORY_TURNS * 2):]
    has_prior_ai = any(isinstance(m, AIMessage) for m in recent)
    prev_form_data = state.get("prev_form_data")
    fill_session = state.get("form_fill_session") or {}
    active_fill = fill_session.get("status") == "collecting"

    # 快速路徑 1：首輪、無候選表、無前輪表單、無進行中填表 → 直接 qa
    if not has_prior_ai and not candidates and not prev_form_data and not active_fill:
        return {
            "intent": "qa",
            "need_retrieval": True,
            "matched_forms": [],
            "form_explicit": False,
            "is_form_continuation": False,
        }

    has_fill_phrase = any(p in query for p in _FILL_TRIGGER_PHRASES)
    has_download_phrase = any(p in query for p in _DOWNLOAD_TRIGGER_PHRASES)
    has_edit_phrase = any(p in query for p in _EDIT_TRIGGER_PHRASES)
    completed_session = fill_session.get("status") == "completed"

    # 快速路徑 2：候選非空 + 明確「填」動詞 + 無「下載」動詞 → 直接 static_form_fill
    # 解決 mini 模型在「我要填X」這類訊息搖擺於 qa/download/fill 的問題
    if candidates and has_fill_phrase and not has_download_phrase:
        target = candidates[0]
        logger.info(
            "[unified_intent] fast-path 2 → static_form_fill, target=%s (candidates=%s)",
            target["form_id"], [c["form_id"] for c in candidates],
        )
        return {
            "intent": "static_form_fill",
            "need_retrieval": False,
            "matched_forms": [target],
            "form_explicit": True,
            "is_form_continuation": False,
        }

    # 快速路徑 3：active fill session + 明確「填」動詞 → 沿用 session 續填
    if active_fill and has_fill_phrase and not has_download_phrase:
        target_id = fill_session.get("target_form_id")
        meta = get_form_meta(target_id) if target_id else None
        if meta:
            logger.info("[unified_intent] fast-path 3 → resume active session %s", target_id)
            return {
                "intent": "static_form_fill",
                "need_retrieval": False,
                "matched_forms": [meta],
                "form_explicit": True,
                "is_form_continuation": False,
            }

    # 快速路徑 4：completed session + 編輯動詞 → 重啟同一份表的編輯（保留已收集值）
    # 處理「填完表後想改某幾欄」的常見訴求
    if completed_session and has_edit_phrase and not has_download_phrase:
        target_id = fill_session.get("target_form_id")
        meta = get_form_meta(target_id) if target_id else None
        if meta:
            logger.info("[unified_intent] fast-path 4 → resume completed session %s for edit", target_id)
            return {
                "intent": "static_form_fill",
                "need_retrieval": False,
                "matched_forms": [meta],
                "form_explicit": True,
                "is_form_continuation": False,
            }

    # ── 組裝 LLM 輸入 ────────────────────────────────────────
    history_lines: list[str] = []
    for msg in recent:
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
            history_lines.append(f"使用者：{msg.content}")
        elif isinstance(msg, AIMessage) and isinstance(msg.content, str):
            history_lines.append(f"AI 助理：{msg.content[:400]}")
    history_text = "\n".join(history_lines) if history_lines else "（無）"

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

    fill_hint = (
        f"進行中填表 session：target_form_id={fill_session.get('target_form_id')}，"
        f"已收集 {len(fill_session.get('collected', {}))} 欄位"
        if active_fill
        else "無進行中填表 session"
    )

    llm = ChatOpenAI(
        model=settings.grader_model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).with_structured_output(IntentDecision)

    decision: IntentDecision = await llm.ainvoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"對話歷史：\n{history_text}\n\n"
            f"當前訊息：{query}\n\n"
            f"候選靜態表：\n{cand_lines}\n\n"
            f"補充資訊：{prev_form_hint}\n{fill_hint}"
        )),
    ])

    # ── 規範化決策（防 LLM 越界輸出）────────────────────────
    intent = decision.intent
    candidate_ids = {c["form_id"] for c in candidates}
    target_id = decision.target_form_id

    # 進行中填表 session 的目標 id 也視為合法
    if active_fill:
        candidate_ids.add(fill_session["target_form_id"])

    if intent in ("static_form_download", "static_form_fill"):
        # fill 進行中時若 LLM 未填 target_id，預設沿用 session 中的
        if not target_id and active_fill:
            target_id = fill_session["target_form_id"]
        if not target_id or target_id not in candidate_ids:
            intent = "qa"

    if intent == "form_continuation" and (
        not prev_form_data or not decision.retrieval_topic
    ):
        intent = "dynamic_form_generate"

    # ── 對應到 graph 後續節點需要的欄位 ──────────────────────
    result: dict = {
        "intent": intent,
        "need_retrieval": decision.need_retrieval,
        "form_explicit": False,
        "is_form_continuation": False,
        "matched_forms": [],
    }

    def _form_meta(form_id: str) -> dict:
        for c in candidates:
            if c["form_id"] == form_id:
                return c
        # session 中的表單可能不在本輪 candidates 內 → 從 registry 重新查
        meta = get_form_meta(form_id)
        return meta or {"form_id": form_id, "display_name": form_id, "download_url": ""}

    if intent == "static_form_download":
        result["matched_forms"] = [_form_meta(target_id)]
        result["form_explicit"] = True
        result["need_retrieval"] = False
    elif intent == "static_form_fill":
        result["matched_forms"] = [_form_meta(target_id)]
        result["form_explicit"] = True
        result["need_retrieval"] = False
    elif intent == "qa":
        # qa 仍可在回應末端提示候選下載（保留既有 UX）
        result["matched_forms"] = candidates
    elif intent == "dynamic_form_generate":
        result["need_retrieval"] = True
    elif intent == "form_continuation":
        result["is_form_continuation"] = True
        result["need_retrieval"] = True
        result["retrieval_query"] = decision.retrieval_topic

    return result

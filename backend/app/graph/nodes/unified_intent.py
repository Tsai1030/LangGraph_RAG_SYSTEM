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
from pydantic import BaseModel, Field

from app.config import settings
from app.core.llm import get_llm
from app.graph.state import GraphState
from app.prompts import get_prompt
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


# _SYSTEM_PROMPT 已搬至 app/prompts/intent/v1.py，使用 get_prompt("intent") 取得


# ──────────────────────────────────────────────────────────────────
# Pure helpers — 純函式，無副作用，易單元測試
# ──────────────────────────────────────────────────────────────────

def _resolve_candidates(query: str, recent_messages: list) -> tuple[list[dict], bool]:
    """候選靜態表查找。回傳 (candidates, from_history)。

    - 先用本輪 query 直接比對 → from_history=False
    - 命不中時 fallback 拼接最近對話再比對 → from_history=True
      （讓使用者第二輪說「我想要填入資訊」無表名時仍能延續上一輪表單）

    呼叫端可依 from_history 決定要不要在 qa 路徑帶上候選表（避免 qa 結尾因歷史
    殘留的舊表名而黏「可下載 X 表」提示）。
    """
    direct = lookup_forms(query)
    if direct:
        return direct, False
    if not recent_messages:
        return [], False
    history_text = " ".join(
        m.content[:_HISTORY_MSG_CHARS]
        for m in recent_messages
        if hasattr(m, "content") and isinstance(m.content, str)
    )
    return (lookup_forms(history_text) if history_text else []), True


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
    doc_names: Optional[list[str]] = None,
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

    doc_hint = (
        f"本對話已上傳文件：{'、'.join(doc_names)}（使用者問題可能針對這些文件內容）"
        if doc_names
        else None
    )

    prompt = (
        f"對話歷史：\n{history_text}\n\n"
        f"當前訊息：{query}\n\n"
        f"候選靜態表：\n{cand_lines}\n\n"
        f"補充資訊：{prev_form_hint}\n{fill_hint}"
    )
    if doc_hint:
        prompt += f"\n{doc_hint}"
    return prompt


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
    candidates_from_history: bool,
) -> dict:
    """根據規範化後的 (intent, target_id) 產生要回給 graph 的 state 變更 dict。

    candidates_from_history=True 代表這批候選是「query 沒命中、從最近對話歷史拼接後再 match」
    得出的。對 static_form_* 仍有用（讓使用者無表名指代時能續用），但 qa 不能帶（會造成
    「鋼筋規範」也黏「動員開工檢核表」的下載提示）。
    """
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
        # qa 只認 query 直接命中的靜態表（讓 responder 在結尾附下載連結）；
        # history fallback 命中的候選不帶 — 避免問新主題時前輪表單一直黏在回覆結尾
        result["matched_forms"] = [] if candidates_from_history else candidates
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
    doc_names: Optional[list[str]] = None,
) -> IntentDecision:
    """單次 LLM call 取得意圖判斷。"""
    history_text = _build_history_text(recent_messages)
    user_prompt = _build_user_prompt(
        query, candidates, prev_form_data, fill_session, history_text, doc_names,
    )

    llm = get_llm("grader", temperature=0).with_structured_output(IntentDecision)

    return await llm.ainvoke([
        SystemMessage(content=get_prompt("intent")),
        HumanMessage(content=user_prompt),
    ])


# ──────────────────────────────────────────────────────────────────
# Graph node 主入口
# ──────────────────────────────────────────────────────────────────

async def unified_intent(state: GraphState) -> dict:
    """主流程：每輪都跑 LLM 分類 → 規範化 → 組 state 變更。

    debug 用 log（grep [unified_intent]）：
      1. INPUT  — 收到的 query / candidates / fill_session / prev_form
      2. LLM    — 模型原始輸出 (intent, target, reason, retrieval_topic, export_format)
      3. STATE  — 規範化後的 state 變更（含 matched_forms 內容）
      若規範化覆寫 intent，會額外印 OVERRIDE 警告。
    """
    query = state["query"]

    messages = state.get("messages", [])
    prior = [m for m in messages[:-1] if isinstance(m, (HumanMessage, AIMessage))]
    recent = prior[-(_MAX_HISTORY_TURNS * 2):]
    prev_form_data = state.get("prev_form_data")
    fill_session = state.get("form_fill_session") or {}

    candidates, candidates_from_history = _resolve_candidates(query, recent)

    logger.info(
        "[unified_intent] INPUT | query=%r | candidates=%s (from_history=%s) | prev_form=%s | "
        "fill_session={status=%s target=%s collected=%d skipped=%d} | history_msgs=%d",
        query,
        [c["form_id"] for c in candidates],
        candidates_from_history,
        (prev_form_data or {}).get("title"),
        fill_session.get("status"),
        fill_session.get("target_form_id"),
        len(fill_session.get("collected", {})),
        len(fill_session.get("skipped_groups", [])),
        len(recent),
    )

    doc_names = [r["filename"] for r in state.get("document_refs") or []]

    # LLM 分類（每輪都打；不再用「首輪→qa」fast-path 因為首輪可能是動態表單請求）
    decision = await _llm_classify(
        query, candidates, prev_form_data, fill_session, recent, doc_names,
    )

    logger.info(
        "[unified_intent] LLM | intent=%s target=%s need_retr=%s | "
        "retrieval_topic=%r export_format=%s | reason=%r",
        decision.intent, decision.target_form_id, decision.need_retrieval,
        decision.retrieval_topic, decision.export_format, decision.reason,
    )

    # 規範化（防 LLM 越界）
    intent, target_id = _normalize_decision(
        decision, candidates, fill_session, prev_form_data,
    )

    if intent != decision.intent or target_id != decision.target_form_id:
        logger.warning(
            "[unified_intent] OVERRIDE | intent %s→%s | target %s→%s",
            decision.intent, intent, decision.target_form_id, target_id,
        )

    update = _build_state_update(intent, target_id, decision, candidates, candidates_from_history)

    # 對話有上傳文件且為 qa → 強制檢索（答案很可能在 session 索引裡，
    # 不能讓 LLM 因問題「看起來不需查 KB」而跳過 retriever）
    if doc_names and update["intent"] == "qa" and not update["need_retrieval"]:
        logger.info("[unified_intent] 已上傳文件 → 強制 need_retrieval=True")
        update["need_retrieval"] = True

    logger.info(
        "[unified_intent] STATE | intent=%s | matched_forms=%s | form_explicit=%s | "
        "need_retrieval=%s | is_form_continuation=%s",
        update["intent"],
        [m.get("form_id") for m in update.get("matched_forms", [])],
        update.get("form_explicit"),
        update.get("need_retrieval"),
        update.get("is_form_continuation"),
    )
    return update

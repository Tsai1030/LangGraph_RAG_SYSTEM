"""
form_fill.py — 靜態表單填寫流程的三個節點

flow（由 builder 串接）：
    unified_intent (intent=static_form_fill)
      └─► form_template_loader  ─ 確保 session 處於可填寫狀態
            └─► form_fill_collector  ─ LLM 抽欄位值 / 批次編輯規格 → code 套用
                  ├─ status=ready ─► form_filler  ─ 寫入 .docx，產出下載 token
                  └─ status=collecting ─► responder（追問）

session 結構（位於 GraphState.form_fill_session，由 checkpointer 跨輪持久化）：
{
  "target_form_id": "010101",
  "collected": {"工程名稱": "...", "tbl0_r2_status": "V"},
  "status": "collecting" | "ready" | "completed",
  "filled_token": "<filename>",       # 完成填寫後設定
  "filled_field_count": int,
  "last_bulk_edit": "...",            # 上一輪批次編輯摘要（responder 引用）
}

設計原則（重構自 regex 版本）：
- LLM 只負責**描述意圖**（單欄抽取、批次編輯規格、是否結束）
- code 負責**列舉與套用**（依 schema 找對應 key、coerce 值、決定 ready/collecting）
- 純函式（_apply_*、_select_*、_format_*、_decide_*）皆無副作用，易單元測試
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.state import GraphState
from app.services.form_fill_writer import load_schema, write_filled_docx

logger = logging.getLogger(__name__)

# 一次最多塞給 LLM 的欄位數（避免 prompt 過長；010315 有 268 欄會被截斷）
_MAX_FIELDS_IN_PROMPT = 120

# 佔位值：auto_fill_test 用（依欄位 type 套用）
_AUTO_FILL_PLACEHOLDERS: dict[str, str] = {
    "checkbox_vx": "V",
    "date": "2026/01/01",
    "text": "test",
}

# checkbox 值正規化字典（小寫比對）
_CHECKBOX_AFFIRMATIVE = {"v", "✓", "✔", "完成", "已完成", "yes", "ok", "1"}
_CHECKBOX_NEGATIVE = {"x", "✗", "✘", "未完成", "未", "no", "0"}

# 給使用者看的填法提示（給 LLM 引用，不直接拼出最終句子）
TYPE_HINT: dict[str, str] = {
    "checkbox_vx": "勾選 V（已完成）或 X（未完成）",
    "date": "日期，格式 YYYY/MM/DD",
    "text": "文字",
}

# label 解析：
#   pattern A: 「編號 2.1「組織提報」 — 完成狀態」 → 檢核項目分組
#   pattern B: 「表 1・第 1 列・版次」              → 表格列分組
# 其他 label（如「工程名稱」「主 辦」）視為獨立欄位，由 group_fields() 合併為「基本資料」
_ITEM_LABEL_RE = re.compile(r"^編號\s*([\d.]+)\s*「(.+?)」\s*[—\-–]\s*(.+)$")
_TBL_LABEL_RE = re.compile(r"^(表\s*\d+)・(第\s*\d+\s*列)・(.+)$")


# ──────────────────────────────────────────────────────────────────
# Schemas — LLM 結構化輸出
# ──────────────────────────────────────────────────────────────────

class _ExtractedField(BaseModel):
    """單一欄位 key → value 抽取（使用者明確指定某欄位的值）。"""
    key: str = Field(description="欄位 key（必須存在於『可填欄位』清單中）")
    value: str = Field(description="該欄位的新值（自由文本；checkbox 用 V/X）")


class _BulkEdit(BaseModel):
    """批次編輯規格：LLM 描述「對哪一群欄位、套用什麼值」，由 code 列舉並套用。

    範例：
      - 「把備註改成 abc」          → label_keywords=["備註"], new_value="abc"
      - 「把備註的 test 改成 123」  → label_keywords=["備註"], old_value="test", new_value="123"
      - 「2.1 的備註改成 done」     → label_keywords=["2.1", "備註"], new_value="done"
      - 「把所有完成狀態打勾」      → label_keywords=["完成狀態"], new_value="V"
    """
    label_keywords: list[str] = Field(
        description="目標欄位的 label 必須**同時包含**的關鍵字（AND）。"
                    "用最少且最精確的關鍵字組合，code 會枚舉所有命中欄位"
    )
    new_value: str = Field(description="要寫入的新值")
    old_value: Optional[str] = Field(
        default=None,
        description="若使用者指定了原值（例『把 test 改成 123』中的 test），"
                    "只更新現值含此字串的欄位；若不指定則更新所有 label 命中者",
    )


class _Extraction(BaseModel):
    extracted: list[_ExtractedField] = Field(
        default_factory=list,
        description="點對點欄位抽取（使用者明確提供某欄位的值）",
    )
    ghost_written: list[_ExtractedField] = Field(
        default_factory=list,
        description="代寫欄位（使用者要求 LLM 自己生內容；只對 type=text 欄位）",
    )
    bulk_edits: list[_BulkEdit] = Field(
        default_factory=list,
        description="批次編輯規格（使用者一次描述更新一群欄位）",
    )
    user_done: bool = Field(
        default=False,
        description="使用者是否表達結束填表（『已完成填寫』『就這樣』『改完了』『OK』）",
    )
    auto_fill_test: bool = Field(
        default=False,
        description="使用者是否要求自動填假資料（『隨便填』『全部 test』）",
    )
    skip_current_group: bool = Field(
        default=False,
        description="使用者是否要求跳過目前項目換到下一個（『跳過這項』『下一個』『先跳過』『不填這個』）。"
                    "與 user_done 區分：user_done 是『結束整張表』，skip 只是換到下個項目。",
    )
    reason: str = Field(description="20 字內判斷依據")


# ──────────────────────────────────────────────────────────────────
# 純函式 — 無副作用（除了傳入的 collected dict 會被原地修改）
# ──────────────────────────────────────────────────────────────────

def _parse_label_group(label: str) -> tuple[str, str, str]:
    """把 label 解析成 (group_id, group_title, sub_label)。

    用於把欄位分組成「使用者語意上同一個項目」（例：同一個檢核編號的 status + remark）。
    若 label 不符合任何已知格式，視為獨立欄位（group_fields 會把連續的獨立欄位合併為「基本資料」）。
    """
    if m := _ITEM_LABEL_RE.match(label):
        no, name, sub = m.group(1), m.group(2).strip(), m.group(3).strip()
        return f"item:{no}", f"{no} {name}", sub
    if m := _TBL_LABEL_RE.match(label):
        tbl, row, sub = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        return f"row:{tbl}-{row}", f"{tbl}・{row}", sub
    return f"single:{label}", label, label


def group_fields(fields: list[dict]) -> list[dict]:
    """把欄位依語意分組，保留 schema 原順序。

    分組策略（優先順序）：
      1. field 顯式提供 `section`：直接以 section 分組，sub_label 用 field.sub_label 或 fallback label
      2. label 符合 _parse_label_group 的兩種 pattern：依 group_id 分組
      3. 其他（連續的獨立欄位）：合併為單一「基本資料」群組

    供 responder 引導使用者「逐項目」填寫；表單填值的 collector 不依賴此函式。
    """
    grouped: list[dict] = []
    by_id: dict[str, dict] = {}
    single_buf: list[dict] = []

    def flush_singles() -> None:
        if not single_buf:
            return
        grouped.append({
            "id": f"basic:{len(grouped)}",
            "title": "基本資料",
            "fields": list(single_buf),
        })
        single_buf.clear()

    def append_to_group(gid: str, gtitle: str, sub_field: dict) -> None:
        flush_singles()
        existing = by_id.get(gid)
        if existing is None:
            existing = {"id": gid, "title": gtitle, "fields": []}
            by_id[gid] = existing
            grouped.append(existing)
        existing["fields"].append(sub_field)

    for f in fields:
        section = f.get("section")
        if section:
            sub = f.get("sub_label") or f["label"]
            append_to_group(f"sec:{section}", section, {**f, "sub_label": sub})
            continue
        gid, gtitle, sub_auto = _parse_label_group(f["label"])
        sub_field = {**f, "sub_label": sub_auto}
        if gid.startswith("single:"):
            single_buf.append(sub_field)
            continue
        append_to_group(gid, gtitle, sub_field)
    flush_singles()
    return grouped


def select_next_group(
    groups: list[dict],
    collected: dict[str, str],
    skipped_group_ids: list[str],
) -> Optional[dict]:
    """挑下一個應該追問的 group。

    優先順序：
      1. 非 skip 過 + 仍有未填欄位的 group（依 schema 順序）
      2. 退一步：skip 過 + 仍有未填欄位的 group（避免完全卡死，最後仍會問到）
      3. 全部填完 → None
    """
    pending = [
        g for g in groups
        if any(f["key"] not in collected for f in g["fields"])
    ]
    non_skipped = [g for g in pending if g["id"] not in skipped_group_ids]
    if non_skipped:
        return non_skipped[0]
    return pending[0] if pending else None


def _coerce_value(value: str, field_type: str) -> str:
    """依欄位 type 正規化值（checkbox 轉 V/X，其他原樣）。"""
    if field_type != "checkbox_vx":
        return value
    low = value.strip().lower()
    if low in _CHECKBOX_AFFIRMATIVE:
        return "V"
    if low in _CHECKBOX_NEGATIVE:
        return "X"
    return value


def _select_visible_fields(fields: list[dict], collected: dict[str, str]) -> list[dict]:
    """挑選給 LLM 看的欄位：required → 未填 optional → 已填 optional（編輯場景需要）。
    截斷在 _MAX_FIELDS_IN_PROMPT 之內。"""
    required = [f for f in fields if f.get("required")]
    optional_unfilled = [f for f in fields if not f.get("required") and f["key"] not in collected]
    optional_filled = [f for f in fields if not f.get("required") and f["key"] in collected]

    visible = required + optional_unfilled
    remaining = max(0, _MAX_FIELDS_IN_PROMPT - len(visible))
    if remaining > 0 and optional_filled:
        visible.extend(optional_filled[:remaining])
    return visible[:_MAX_FIELDS_IN_PROMPT]


def _format_field_lines(visible: list[dict], collected: dict[str, str]) -> str:
    """把欄位清單格式化成 LLM 可讀的條列。"""
    return "\n".join(
        f"- key={f['key']}  type={f['type']}  required={f.get('required', False)}"
        f"  current={collected.get(f['key'], '')!r}  label={f['label']}"
        for f in visible
    )


def _apply_extracted(
    extracted: list[_ExtractedField],
    fields: list[dict],
    collected: dict[str, str],
    *,
    text_only: bool = False,
) -> list[str]:
    """把單欄抽取結果寫入 collected，回傳成功寫入的 key 清單。

    Args:
        text_only: True 時只允許 type=text 欄位（用於 ghost_written 防呆）
    """
    field_by_key = {f["key"]: f for f in fields}
    applied: list[str] = []
    for ext in extracted:
        f = field_by_key.get(ext.key)
        if f is None or not ext.value:
            continue
        if text_only and f.get("type") != "text":
            continue
        collected[ext.key] = _coerce_value(ext.value, f.get("type", "text"))
        applied.append(ext.key)
    return applied


def _apply_bulk_edits(
    bulk_edits: list[_BulkEdit],
    fields: list[dict],
    collected: dict[str, str],
) -> tuple[int, Optional[str]]:
    """套用批次編輯規格。

    Returns:
        (套用的欄位總數, 給人讀的摘要 or None)
    """
    if not bulk_edits:
        return 0, None

    total = 0
    summaries: list[str] = []
    for spec in bulk_edits:
        keywords = [kw for kw in spec.label_keywords if kw]
        if not keywords or not spec.new_value:
            continue
        applied = 0
        for f in fields:
            label = f.get("label", "")
            if not all(kw in label for kw in keywords):
                continue
            if spec.old_value:
                current = str(collected.get(f["key"], ""))
                if spec.old_value not in current:
                    continue
            collected[f["key"]] = _coerce_value(spec.new_value, f.get("type", "text"))
            applied += 1
        if applied:
            kw_label = " + ".join(f"「{k}」" for k in keywords)
            summaries.append(f"{applied} 個含{kw_label}的欄位 → 「{spec.new_value}」")
            total += applied

    if total == 0:
        return 0, None
    return total, "；".join(summaries)


def _apply_auto_fill_test(fields: list[dict], collected: dict[str, str]) -> int:
    """為仍未填的欄位套上型別對應的佔位值，回傳填入筆數。"""
    n = 0
    for f in fields:
        if f["key"] in collected:
            continue
        collected[f["key"]] = _AUTO_FILL_PLACEHOLDERS.get(f.get("type", "text"), "test")
        n += 1
    return n


def _decide_status(
    extraction: _Extraction,
    n_bulk: int,
    fields: list[dict],
    collected: dict[str, str],
) -> str:
    """決定本輪結束時 session.status：
    - auto_fill_test：直接 ready
    - 有批次編輯：強制 collecting（等使用者再說『已完成填寫』確認，避免 LLM 把『改成 X』誤判 user_done=True）
    - 否則：由 LLM 的 user_done + required 欄位是否齊全決定
    """
    if extraction.auto_fill_test:
        return "ready"
    if n_bulk > 0:
        return "collecting"
    required_keys = {f["key"] for f in fields if f.get("required")}
    required_filled = required_keys.issubset(collected.keys())
    if extraction.user_done and (required_filled or not required_keys):
        return "ready"
    return "collecting"


# ──────────────────────────────────────────────────────────────────
# LLM wrapper
# ──────────────────────────────────────────────────────────────────

_COLLECTOR_SYSTEM = """\
你是表單填寫助理。從使用者訊息中**抽取意圖**（不要列舉所有 key），輸出 JSON。

【四種輸出（互不衝突，可並存）】

1. extracted — 點對點欄位抽取
   使用者明確提供「某 label 的值是 X」時用。
   範例：「工程名稱叫和平大樓」→ extracted=[{key:"工程名稱", value:"和平大樓"}]
   - key 必須存在於『可填欄位』清單中
   - checkbox 類型用 V / X；text / date 保留原文

2. ghost_written — 代寫欄位（使用者請你自己擬內容）
   使用者用「幫我寫」「代寫」「擬一個」「自動產生」「寫一段」這類動詞 → 你自己生內容並放入 ghost_written。
   範例：
   - 「幫我寫一段簡短的計畫填進計畫書內容」
     → ghost_written=[{key:"計畫書內容", value:"本工程主要施作 XX 項目，預計 N 個月完工，包含 ..."}]
   - 「幫我擬個說明文字」（若有 label 含「說明」「描述」「內容」之類的 text 欄位）
     → ghost_written=[{key:<該欄位 key>, value:<你擬的內容>}]
   要點：
   - **只對 type=text 欄位**有效；checkbox 與 date 必須使用者提供具體值，不可代寫
   - 內容應符合 label 語意，**簡短合理（建議 1-3 句）**
   - 若使用者沒指定哪個欄位，挑 label 最相關的；若無對應 → 不要硬填，回 ghost_written=[]
   - **與 auto_fill_test 區分**：使用者說「全部填 test/隨便填」走 auto_fill_test（佔位值）；
     說「幫我寫某欄位」才是 ghost_written（生真實內容）

3. bulk_edits — 批次編輯規格
   使用者一次描述「對一群欄位做相同更新」時用。
   你只要描述條件（label_keywords + new_value），**不要列出所有 key**；code 會自己枚舉。
   範例：
   - 「把備註改成 abc」          → bulk_edits=[{label_keywords:["備註"], new_value:"abc"}]
   - 「把備註的 test 改成 123」  → bulk_edits=[{label_keywords:["備註"], old_value:"test", new_value:"123"}]
   - 「2.1 的備註改成 done」     → bulk_edits=[{label_keywords:["2.1","備註"], new_value:"done"}]
   - 「全部完成狀態打勾」        → bulk_edits=[{label_keywords:["完成狀態"], new_value:"V"}]
   - 「把備註清空」              → bulk_edits=[{label_keywords:["備註"], new_value:""}]
   要點：
   - label_keywords 是 AND 邏輯（label 必須同時包含每一個關鍵字）
   - 用**最少且最精確**的關鍵字
   - 若使用者指定原值（『把 test 改成 X』），用 old_value 限定範圍

4. user_done / auto_fill_test
   - user_done=true 限定**結束指令**：「已完成填寫」「就這樣」「都填好了」「OK」「完成」「改完了」「改好了」
   - **絕對不要**因為訊息含「改成 X」「改為 X」「幫我寫」就 user_done=true（這些是執行動作，不是結束）
   - auto_fill_test=true：「全部填 test」「隨便填」「自動填」「填假資料」（套佔位值，與 ghost_written 不同）

5. skip_current_group — 換到下一個項目
   - 觸發：「繼續填寫下一頁」「下一頁」「下一項」「下一個」「跳過這項」「跳過」「先跳過」「不填這個」「換下一個」「先填別的」
   - 與 user_done 區分：user_done 結束**整張表**；skip 只是換到**下一個項目**繼續填
   - 與 extracted/bulk_edits 可並存：「繼續填寫下一頁，附件 3 第 1 列文件名稱叫 ABC」→ skip=true + extracted=[...]

【關鍵原則】
- 看不懂訊息：所有 list 為空，user_done=false, auto_fill_test=false
- 同個欄位重複提及取最新值
- reason 用 20 字內中文說明依據"""


async def _llm_extract(
    query: str,
    fields: list[dict],
    collected: dict[str, str],
) -> _Extraction:
    """單次 LLM call 取得抽取結果。"""
    visible = _select_visible_fields(fields, collected)
    field_lines = _format_field_lines(visible, collected)

    user_prompt = (
        f"使用者訊息：{query}\n\n"
        f"已收集欄位數：{len(collected)}\n\n"
        f"可填欄位（節錄前 {len(visible)}）：\n{field_lines}"
    )

    llm = ChatOpenAI(
        model=settings.grader_model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).with_structured_output(_Extraction)

    return await llm.ainvoke([
        SystemMessage(content=_COLLECTOR_SYSTEM),
        HumanMessage(content=user_prompt),
    ])


# ──────────────────────────────────────────────────────────────────
# Graph nodes — 編排
# ──────────────────────────────────────────────────────────────────

async def form_template_loader(state: GraphState) -> dict:
    """確保 form_fill_session 處於可填寫狀態。

    決策：
      - 無 session → 開新 session（target = unified_intent 給的 form_id）
      - 有 session 但 target 不同 → 切表 → 重置（清掉 collected）
      - 有 session 同表 status=collecting → 維持
      - 有 session 同表 status=completed → 重啟為 collecting，保留 collected（編輯場景）
      - 有 session 同表 status=error → 重置
    """
    session = state.get("form_fill_session") or {}

    target_id_from_intent: Optional[str] = None
    matched = state.get("matched_forms") or []
    if matched:
        target_id_from_intent = matched[0].get("form_id")

    target_id = target_id_from_intent or session.get("target_form_id")
    if not target_id:
        logger.warning("[form_template_loader] 沒有 target_form_id，無法載入 schema")
        return {}

    schema = load_schema(target_id)
    if schema is None:
        logger.warning("[form_template_loader] schema 不存在: %s", target_id)
        return {"form_fill_session": {"target_form_id": target_id, "status": "error", "collected": {}}}

    prior_target = session.get("target_form_id")
    prior_status = session.get("status")

    query = state.get("query", "")
    if not session or prior_target != target_id or prior_status == "error":
        new_session = {"target_form_id": target_id, "collected": {}, "status": "collecting"}
        logger.info(
            "[form_template_loader] new/switch → target=%s (was target=%s status=%s) | query=%r",
            target_id, prior_target, prior_status, query,
        )
    elif prior_status == "completed":
        new_session = {**session, "status": "collecting"}
        new_session.pop("filled_token", None)
        new_session.pop("filled_field_count", None)
        logger.info(
            "[form_template_loader] resume completed for edit → target=%s, %d fields preserved | query=%r",
            target_id, len(new_session.get("collected", {})), query,
        )
    else:
        new_session = session
        logger.info(
            "[form_template_loader] continue collecting → target=%s, %d fields collected | query=%r",
            target_id, len(session.get("collected", {})), query,
        )

    return {"form_fill_session": new_session}


async def form_fill_collector(state: GraphState) -> dict:
    """從本輪 query 抽取意圖（單欄 / 批次 / 結束 / 自動填）並套用到 collected。"""
    session = state.get("form_fill_session") or {}
    if session.get("status") != "collecting":
        return {}

    target_id = session["target_form_id"]
    schema = load_schema(target_id)
    if schema is None:
        return {}

    fields = schema["fields"]
    collected: dict[str, str] = dict(session.get("collected", {}))
    skipped_groups: list[str] = list(session.get("skipped_groups", []))

    # 記下 user 看到的 (pre-edit) 狀態，供 skip 計算「使用者當下看到的是哪個 group」
    pre_collected = dict(collected)
    pre_skipped = list(skipped_groups)

    extraction = await _llm_extract(state["query"], fields, collected)

    extracted_keys = _apply_extracted(extraction.extracted, fields, collected)
    ghost_keys = _apply_extracted(extraction.ghost_written, fields, collected, text_only=True)
    n_bulk, bulk_summary = _apply_bulk_edits(extraction.bulk_edits, fields, collected)
    n_auto = _apply_auto_fill_test(fields, collected) if extraction.auto_fill_test else 0

    if extraction.skip_current_group:
        focused = select_next_group(group_fields(fields), pre_collected, pre_skipped)
        if focused and focused["id"] not in skipped_groups:
            skipped_groups.append(focused["id"])

    status = _decide_status(extraction, n_bulk, fields, collected)

    new_session: dict = {
        **session,
        "collected": collected,
        "skipped_groups": skipped_groups,
        "status": status,
    }
    if bulk_summary:
        new_session["last_bulk_edit"] = bulk_summary
    else:
        new_session.pop("last_bulk_edit", None)
    if ghost_keys:
        new_session["last_ghost_written"] = ghost_keys
    else:
        new_session.pop("last_ghost_written", None)

    logger.info(
        "[form_fill_collector] form=%s extracted=%d ghost=%d bulk=%d auto=%d skipped=%d "
        "collected=%d user_done=%s auto_test=%s skip=%s → status=%s | query=%r | reason=%r",
        target_id, len(extracted_keys), len(ghost_keys), n_bulk, n_auto, len(skipped_groups),
        len(collected), extraction.user_done, extraction.auto_fill_test,
        extraction.skip_current_group, status, state.get("query", ""), extraction.reason,
    )
    return {"form_fill_session": new_session}


def form_filler(state: GraphState) -> dict:
    """將 session.collected 寫入模板 .docx 副本，產出下載 token。"""
    session = state.get("form_fill_session") or {}
    if session.get("status") != "ready":
        return {}

    target_id = session["target_form_id"]
    collected = session.get("collected", {})
    conv_id = state.get("conversation_id", "anonymous")

    result = write_filled_docx(target_id, collected, conv_id)
    if result is None:
        return {"form_fill_session": {**session, "status": "error"}}

    out_path, written = result
    return {"form_fill_session": {
        **session,
        "status": "completed",
        "filled_token": out_path.name,
        "filled_field_count": written,
    }}

"""
generation.py — 回覆生成節點

使用 ChatOpenAI 生成回覆。
streaming=True 使 LangGraph 的 astream_events 可捕捉 on_chat_model_stream 事件，
讓 chat endpoint 可逐 token 推送 SSE。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.graph.state import GraphState

_SYSTEM_PROMPT_TEMPLATE = """\
你是一位熟悉公司規範的營造業顧問，服務對象是公司內部員工。
請閱讀下方參考文件，**充分理解內容脈絡後**，用自己的話回答員工的問題。

回答方式：
1. 先建立概念框架：若問題涉及分級、範疇或定義，先用一句話說明「這是什麼」（例如：金額範圍、適用情境），讓員工有背景知識再看流程
2. 按邏輯重新組織：不照抄文件段落順序，改依「準備→執行→完成」等實際操作邏輯分階段說明，並加上小標題
3. 整合散落資訊：若文件不同小節都有相關內容（流程、應備文件、注意事項、金額標準），主動整合到同一個回答裡，不要讓員工自己去拼湊
4. 禁止大段複製文件原文：用自己的語言重述，保留關鍵術語與數字即可
5. 圖片引用（重要）：
   - 引用圖片時**只能**用 Markdown 語法：![圖片說明](路徑)，路徑維持 /api/images/... 不變
   - **禁止**寫出「圖片路徑：」、「IMG-XXX」、圖片 ID 等純文字標籤
   - 當圖片能直接輔助說明時再引用，每次回答通常 1–3 張為宜，不需逐一列出所有圖片
6. 若本次已生成動態表單（將在 [本次表單] 區塊提供 columns / rows）：
   - 用 **Markdown 表格語法**直接寫進回答中，讓使用者一眼看到完整表格內容
   - 用 `### 表單標題` 起頭；columns 用 `| 欄位1 | 欄位2 | ... |` 開頭，下一行 `|---|---|...|` 分隔
   - 每一列照 columns 順序輸出 row 的值
   - **末段務必加一句**：「如需匯出為 Excel 或 CSV 下載，請告訴我格式即可。」
   - 嚴禁省略表格內容只說「已生成《標題》」這類確認語
7. 若使用者只是寒暄（hi、hello、你好、嗨、哈囉、早安、謝謝等）、訊息過短無實質主題、或問題完全不在文件範圍內：
   - **不要**回「目前知識庫未涵蓋此資訊」「沒有可參考的內部文件」這類冷淡句
   - **不要**列主題清單或條列項目
   - 用**輕鬆一句話**回覆（30–60 字），先打招呼再開放式詢問需求，並順帶提到可協助公司規範或營造流程
   - 範例：「HI！今天想聊什麼或需要我幫你做什麼？或想了解哪一項公司規範或營造流程呢？」
   - 風格自然口語，不要過於正式
8. 使用繁體中文，語氣專業但自然口語
9. **禁止**使用「依文件」、「文件中提到」、「文件明確指出」、「根據文件」、「依據文件」等引用性措辭，直接陳述內容

{summary_section}
[參考文件]
{context}{form_section}"""

_DYNAMIC_FORM_EXPORT_DONE_SYSTEM = """\
動態表單已匯出為下載檔。請用一句繁體中文（30字內）告知使用者並提示點擊下方下載。
範例：「已將《標題》匯出為 Excel，請點選下方下載。」
直接從「已將」或「已為您匯出」開始；禁止確認語。"""


def _build_form_section(form_data: dict) -> str:
    """把動態表單的完整內容包進 prompt，讓 LLM 用 markdown 表格輸出。"""
    import json as _json

    title = form_data.get("title", "表單")
    columns = form_data.get("columns", [])
    rows = form_data.get("rows", [])
    subtitle = form_data.get("subtitle") or ""
    notes = form_data.get("notes") or ""

    return (
        f"\n\n[本次表單]\n"
        f"title：{title}\n"
        + (f"subtitle：{subtitle}\n" if subtitle else "")
        + f"columns：{_json.dumps(columns, ensure_ascii=False)}\n"
        + f"rows（共 {len(rows)} 列）：\n"
        + _json.dumps(rows, ensure_ascii=False, indent=2)
        + (f"\nnotes：{notes}" if notes else "")
        + "\n（請依 system prompt 規則 6 用 markdown 表格輸出此表單）"
    )


def _build_messages(state: GraphState) -> list[BaseMessage]:
    """
    組裝送給 LLM 的訊息列表：
    [System(RAG context + summary + form_data)] + [對話歷史中的 human/ai 訊息]
    """
    summary = state.get("summary")
    summary_section = f"[前情摘要]\n{summary}\n" if summary else ""

    form_data = state.get("form_data")
    form_section = _build_form_section(form_data) if form_data else ""

    # QA 模式且有匹配靜態表單 → 在回答末尾加提示
    matched_forms = state.get("matched_forms", [])
    form_explicit = state.get("form_explicit", False)
    form_offer_hint = ""
    if matched_forms and not form_explicit and not form_data:
        names = "、".join(f"《{f['display_name']}》" for f in matched_forms)
        form_offer_hint = f"\n[表單提示]\n回答結束後，在最後一行加上一句：「如需相關作業表單，可點擊下方 {names} 下載。」"

    system_content = _SYSTEM_PROMPT_TEMPLATE.format(
        summary_section=summary_section,
        context=state.get("context") or "（無相關文件）",
        form_section=form_section,
    ) + form_offer_hint

    msgs: list[BaseMessage] = [SystemMessage(content=system_content)]

    # 加入對話歷史（只取 human/ai 訊息）
    for msg in state.get("messages", []):
        if isinstance(msg, (HumanMessage, AIMessage)):
            msgs.append(msg)

    return msgs


_STATIC_FORM_SYSTEM = """\
使用者明確索取了一份作業表單。請用一句繁體中文（20字以內）提示使用者點擊下方下載。
格式範例：《表單名稱》，請點擊下方下載。
禁止在句首加上「已找到」、「為您找到」等確認語，直接從《表單名稱》開始。"""


_FILL_COLLECT_SYSTEM = """\
你是表單填寫助理，正引導使用者把資料填入靜態表單。請以繁體中文簡潔回應（≤180 字）。

【目標】讓使用者「一眼看懂在填什麼」，不必看欄位編號或 key 即可作答。

【回應結構（依序）】
1. 開頭一句：以「《表單名稱》進度 N／M」起頭，並說明本輪做了什麼
   - 首次進入（is_first_turn=true）說「已開始填寫」
   - 其他情況說「已收到 X 欄／已完成 N 個批次更新／已代寫 N 個欄位」其中之一
2. 主體（聚焦 user prompt 提供的「目前項目」，不要跨項目）：
   - 第一行寫項目標題（例：「目前項目：2.1 組織提報」）
   - 之後每行一個子欄位，格式：
       - <子欄位名>：<填法提示>（已填則加上『已填：xxx』、未填則加上『待填』）
   - 填法提示直接引用 user prompt 的「類型提示」字串
3. 若 is_first_turn=true，接一行示範：「例：『已完成，備註 OK』」（用真實項目語意改寫）
4. 若本輪有「AI 代寫的欄位」：再加一段「我幫你寫了：」逐欄列出代寫內容，告知可說「把 X 改成 Y」修改
5. 結尾固定獨立一行（與主體空一行）：
     輸入「已完成填寫」立即產出檔案；想換到下個項目輸入「繼續填寫下一頁」；或「全部填 test」一鍵補滿測試值。

【嚴禁】
- 一次跨多個項目（只能聚焦 user prompt 給的「目前項目」）
- 列出欄位 key（如 tbl0_r2_status）
- markdown 表格、編號清單序號（用「- 」即可）
- 在 is_first_turn=false 時重複示範語句"""

_FILL_DONE_SYSTEM = """\
表單已填寫完成。請用一句繁體中文（30字內）告知使用者並提示點擊下方下載。
範例：「已將您的資料填入《動員開工作業檢核表》，請點選下方下載。」
直接從「已將」或「已為您填好」開始；禁止確認語。"""


def _build_fill_collect_user(state: GraphState) -> str:
    """組裝填表追問用的 user prompt。

    與 _FILL_COLLECT_SYSTEM 配合：把 schema 解析成「使用者語意上同一個項目」的群組，
    每輪只暴露第一個尚未完成的群組給 LLM，並附上每個子欄位的填法提示與當前值。
    """
    from app.graph.nodes.form_fill import TYPE_HINT, group_fields, select_next_group
    from app.services.form_fill_writer import load_schema

    session = state.get("form_fill_session") or {}
    target_id = session.get("target_form_id")
    schema = load_schema(target_id) if target_id else None
    title = (schema or {}).get("title", "靜態表單")
    fields = (schema or {}).get("fields", [])
    collected = session.get("collected", {})
    skipped_groups: list[str] = session.get("skipped_groups", [])

    groups = group_fields(fields)
    pending_groups = [
        g for g in groups
        if any(f["key"] not in collected for f in g["fields"])
    ]
    next_group = select_next_group(groups, collected, skipped_groups)

    bulk_edit = session.get("last_bulk_edit")
    ghost_keys = session.get("last_ghost_written") or []
    ghost_items = [
        {"label": next((f["label"] for f in fields if f["key"] == k), k),
         "value": collected.get(k, "")}
        for k in ghost_keys
    ]
    is_first_turn = not collected and not bulk_edit and not ghost_items

    parts = [
        f"目標表單：{title}",
        f"使用者本輪訊息：{state['query']}",
        f"進度：{len(collected)} / {len(fields)} 欄已填，剩 {len(pending_groups)} 個項目"
        + (f"（已跳過 {len(skipped_groups)} 個）" if skipped_groups else ""),
        f"is_first_turn：{str(is_first_turn).lower()}",
    ]
    if ghost_items:
        ghost_lines = "\n".join(
            f"- {it['label']}：{it['value'][:80]}{'…' if len(it['value']) > 80 else ''}"
            for it in ghost_items
        )
        parts.append(f"本輪 AI 代寫的欄位（請在回應中讓使用者過目並可改）：\n{ghost_lines}")
    if bulk_edit:
        parts.append(f"本輪批次編輯結果：{bulk_edit}")

    if next_group:
        sub_lines = []
        for f in next_group["fields"]:
            hint = TYPE_HINT.get(f.get("type", "text"), "文字")
            cur = collected.get(f["key"], "")
            state_str = f"已填：{cur}" if cur else "待填"
            sub_lines.append(f"- {f['sub_label']}（類型提示：{hint}；{state_str}）")
        parts.append(
            f"目前項目：{next_group['title']}\n"
            f"本項目欄位（請依此引導使用者）：\n" + "\n".join(sub_lines)
        )
    else:
        parts.append("已沒有未填欄位，請告訴使用者：「全部欄位都已填寫，輸入『已完成填寫』即可下載填好的檔案」")
    return "\n".join(parts)


async def responder(state: GraphState) -> dict:
    """
    生成回覆。intent 與 fill session 決定使用哪一種 prompt：
    - static_form_fill + status=completed → 短確認句 + 下載連結提示
    - static_form_fill + status=collecting → 追問仍缺欄位
    - static_form_download → 短確認句
    - 其他 → 完整 RAG 生成
    streaming=True：配合 astream_events 讓 chat endpoint 逐 token 推送 SSE。
    """
    intent = state.get("intent")
    matched_forms = state.get("matched_forms", [])
    form_explicit = state.get("form_explicit", False)
    session = state.get("form_fill_session") or {}

    # ── 填表完成 ─────────────────────────────────────────────
    if intent == "static_form_fill" and session.get("status") == "completed":
        names = "、".join(f"《{f['display_name']}》" for f in matched_forms) or "《表單》"
        llm = ChatOpenAI(
            model=settings.grader_model,
            api_key=settings.openai_api_key,
            temperature=0,
            streaming=True,
        )
        resp = await llm.ainvoke([
            SystemMessage(content=_FILL_DONE_SYSTEM),
            HumanMessage(content=f"目標：{names}；已寫入 {session.get('filled_field_count', 0)} 欄位"),
        ])
        return {"response": resp.content, "messages": [AIMessage(content=resp.content)]}

    # ── 填表收集中（追問缺欄位）────────────────────────────
    if intent == "static_form_fill" and session.get("status") == "collecting":
        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            temperature=0.3,
            streaming=True,
        )
        resp = await llm.ainvoke([
            SystemMessage(content=_FILL_COLLECT_SYSTEM),
            HumanMessage(content=_build_fill_collect_user(state)),
        ])
        return {"response": resp.content, "messages": [AIMessage(content=resp.content)]}

    # ── 動態表單匯出：短確認句 ─────────────────────────────
    if intent == "dynamic_form_export":
        exported = state.get("exported_form_file") or {}
        title = exported.get("display_name") or "表單"
        if exported:
            llm = ChatOpenAI(
                model=settings.grader_model,
                api_key=settings.openai_api_key,
                temperature=0,
                streaming=True,
            )
            resp = await llm.ainvoke([
                SystemMessage(content=_DYNAMIC_FORM_EXPORT_DONE_SYSTEM),
                HumanMessage(content=f"匯出檔：{title}"),
            ])
            return {"response": resp.content, "messages": [AIMessage(content=resp.content)]}
        # 匯出失敗（無 prev_form_data 等）→ 落入下方一般 RAG 路徑提供錯誤訊息

    # ── 靜態表單下載：短確認句 ─────────────────────────────
    if intent == "static_form_download" and form_explicit and matched_forms:
        names = "、".join(f"《{f['display_name']}》" for f in matched_forms)
        llm = ChatOpenAI(
            model=settings.grader_model,
            api_key=settings.openai_api_key,
            temperature=0,
            streaming=True,
        )
        response = await llm.ainvoke([
            SystemMessage(content=_STATIC_FORM_SYSTEM),
            HumanMessage(content=f"找到：{names}"),
        ])
        return {
            "response": response.content,
            "messages": [AIMessage(content=response.content)],
        }

    # ── 一般 QA / 動態表單生成 ─────────────────────────────
    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        temperature=0.6,
        streaming=True,
    )

    prompt_messages = _build_messages(state)
    response = await llm.ainvoke(prompt_messages)

    return {
        "response": response.content,
        "messages": [AIMessage(content=response.content)],
    }

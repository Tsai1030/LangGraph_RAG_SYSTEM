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
6. 若本次已生成表單，**只需一句話確認**（例如：「已為您生成《標題》，請點選下方按鈕下載。」），**嚴禁**在文字中重複輸出表格、欄位名稱或條列式資料
7. 若使用者問題不在文件範圍內，明確說明「目前知識庫未涵蓋此資訊」
8. 使用繁體中文，語氣專業但自然口語
9. **禁止**使用「依文件」、「文件中提到」、「文件明確指出」、「根據文件」、「依據文件」等引用性措辭，直接陳述內容

{summary_section}
[參考文件]
{context}"""


def _build_messages(state: GraphState) -> list[BaseMessage]:
    """
    組裝送給 LLM 的訊息列表：
    [System(RAG context + summary)] + [對話歷史中的 human/ai 訊息]

    注意：只取 HumanMessage / AIMessage，排除 SystemMessage，
    避免 compact 後的 system summary 重複出現。
    """
    summary = state.get("summary")
    summary_section = f"[前情摘要]\n{summary}\n" if summary else ""

    # 動態表單提示（若本次有生成 form_structurer 表單）
    form_data = state.get("form_data")
    form_hint = ""
    if form_data:
        title = form_data.get("title", "表單")
        row_count = len(form_data.get("rows", []))
        form_hint = f"\n[本次已生成表單：「{title}」，共 {row_count} 筆資料]"

    # QA 模式且有匹配靜態表單 → 在回答末尾加提示
    matched_forms = state.get("matched_forms", [])
    form_explicit = state.get("form_explicit", False)
    form_offer_hint = ""
    if matched_forms and not form_explicit:
        names = "、".join(f"《{f['display_name']}》" for f in matched_forms)
        form_offer_hint = f"\n[表單提示]\n回答結束後，在最後一行加上一句：「如需相關作業表單，可點擊下方 {names} 下載。」"

    system_content = _SYSTEM_PROMPT_TEMPLATE.format(
        summary_section=summary_section,
        context=state.get("context") or "（無相關文件）",
    ) + form_hint + form_offer_hint

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
你是表單填寫助理，正引導使用者把資料填入靜態表單。請以繁體中文簡潔回應（120字內）。

回應原則：
- 先一句確認本輪做了什麼（收到欄位 / 完成批次編輯 / 代寫了內容）
- 若本輪有「AI 代寫的欄位」：**完整列出代寫內容讓使用者過目**（一個欄位一行），告知可說「把 X 改成 Y」修改
- 若仍有待填欄位：列出下一批 3-5 個關鍵欄位 label
- 末段務必清楚提示兩個選項：
  1. 一次描述多個欄位繼續補（或對代寫內容說『改成…』修改）
  2. **輸入「就這樣」或「全部填 test」可立即產出填好的檔案下載**
- 嚴禁列出超過 5 個未填欄位
- 嚴禁輸出 markdown 表格或欄位 key（如 tbl0_r2_status）"""

_FILL_DONE_SYSTEM = """\
表單已填寫完成。請用一句繁體中文（30字內）告知使用者並提示點擊下方下載。
範例：「已將您的資料填入《動員開工作業檢核表》，請點選下方下載。」
直接從「已將」或「已為您填好」開始；禁止確認語。"""


def _build_fill_collect_user(state: GraphState) -> str:
    """組裝填表追問用的 user prompt：本輪訊息 + 已收集 + 仍缺欄位 label 清單"""
    from app.services.form_fill_writer import load_schema

    session = state.get("form_fill_session") or {}
    target_id = session.get("target_form_id")
    schema = load_schema(target_id) if target_id else None
    title = (schema or {}).get("title", "靜態表單")
    fields = (schema or {}).get("fields", [])
    collected = session.get("collected", {})

    required_pending = [f for f in fields if f.get("required") and f["key"] not in collected]
    optional_pending = [f for f in fields if not f.get("required") and f["key"] not in collected]
    next_batch = required_pending + optional_pending[: max(0, 5 - len(required_pending))]
    next_batch = next_batch[:5]

    pending_labels = [f["label"] for f in next_batch]
    total_pending = len(required_pending) + len(optional_pending)
    bulk_edit = session.get("last_bulk_edit")
    ghost_keys = session.get("last_ghost_written") or []
    ghost_items = [
        {"label": next((f["label"] for f in fields if f["key"] == k), k),
         "value": collected.get(k, "")}
        for k in ghost_keys
    ]

    parts = [
        f"目標表單：{title}",
        f"使用者本輪訊息：{state['query']}",
        f"已收集欄位總數：{len(collected)} / {len(fields)}",
    ]
    if ghost_items:
        ghost_lines = "\n".join(
            f"- {it['label']}：{it['value'][:80]}{'…' if len(it['value']) > 80 else ''}"
            for it in ghost_items
        )
        parts.append(f"本輪 AI 代寫的欄位（請在回應中讓使用者過目並可改）：\n{ghost_lines}")
    if bulk_edit:
        parts.append(f"本輪批次編輯結果：{bulk_edit}")
    parts.append(f"仍待填欄位總數：{total_pending}")
    if pending_labels:
        parts.append("下一批請追問的欄位 label：\n" + "\n".join(f"- {l}" for l in pending_labels))
    else:
        parts.append("已沒有未填欄位，請告訴使用者：「全部欄位都已填寫，輸入『就這樣』即可下載填好的檔案」")
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

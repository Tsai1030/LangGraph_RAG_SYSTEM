"""
generation.py — 回覆生成節點

LLM 透過 app.core.llm.get_llm() factory 取得（provider 由 .env 切換）。
streaming=True 使 LangGraph 的 astream_events 可捕捉 on_chat_model_stream 事件，
讓 chat endpoint 可逐 token 推送 SSE。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.config import settings
from app.core.llm import get_llm
from app.graph.state import GraphState
from app.prompts import get_prompt
from app.services.image_store import to_image_block


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
    [System(RAG context + summary + form_data + 圖片解析)] + [對話歷史中的 human/ai 訊息]

    有上傳圖片（image_refs）時，把原圖附到當輪 HumanMessage（多模態），讓 Gemini
    生成前能再核對原圖像素（D4）。原圖只進本次 LLM call，不寫回 state.messages。
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

    # 圖片解析（vision_intake 產出）→ 注入 system context 作 grounding
    image_understanding = state.get("image_understanding")
    image_section = (
        f"\n\n[使用者上傳圖片的內容解析]\n{image_understanding}\n（請結合上述圖片內容回答使用者問題）"
        if image_understanding else ""
    )

    system_content = get_prompt("responder.qa").format(
        summary_section=summary_section,
        context=state.get("context") or "（無相關文件）",
        form_section=form_section,
    ) + form_offer_hint + image_section

    msgs: list[BaseMessage] = [SystemMessage(content=system_content)]

    # 加入對話歷史（只取 human/ai 訊息）；當輪 HumanMessage 若有上傳圖片，附原圖（多模態）
    history = [m for m in state.get("messages", []) if isinstance(m, (HumanMessage, AIMessage))]
    image_refs = state.get("image_refs") or []
    image_blocks = [b for ref in image_refs if (b := to_image_block(ref)) is not None]
    last_idx = len(history) - 1
    for i, msg in enumerate(history):
        if image_blocks and i == last_idx and isinstance(msg, HumanMessage):
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            msgs.append(HumanMessage(content=[{"type": "text", "text": text}, *image_blocks]))
        else:
            msgs.append(msg)

    return msgs


def _build_fill_collect_user(state: GraphState) -> str:
    """組裝填表追問用的 user prompt。

    與 prompts.responder.fill_collect_v1 配合：把 schema 解析成「使用者語意上同一個項目」的群組，
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
        llm = get_llm("grader", temperature=0, streaming=True, stream_usage=True)
        resp = await llm.ainvoke([
            SystemMessage(content=get_prompt("responder.fill_done")),
            HumanMessage(content=f"目標：{names}；已寫入 {session.get('filled_field_count', 0)} 欄位"),
        ])
        text = getattr(resp, "text", None) or (resp.content if isinstance(resp.content, str) else "")
        return {"response": text, "messages": [AIMessage(content=text)]}

    # ── 填表收集中（追問缺欄位）────────────────────────────
    if intent == "static_form_fill" and session.get("status") == "collecting":
        llm = get_llm("default", temperature=0.3, streaming=True, stream_usage=True)
        resp = await llm.ainvoke([
            SystemMessage(content=get_prompt("responder.fill_collect")),
            HumanMessage(content=_build_fill_collect_user(state)),
        ])
        text = getattr(resp, "text", None) or (resp.content if isinstance(resp.content, str) else "")
        return {"response": text, "messages": [AIMessage(content=text)]}

    # ── 動態表單匯出：短確認句 ─────────────────────────────
    if intent == "dynamic_form_export":
        exported = state.get("exported_form_file") or {}
        title = exported.get("display_name") or "表單"
        if exported:
            llm = get_llm("grader", temperature=0, streaming=True, stream_usage=True)
            resp = await llm.ainvoke([
                SystemMessage(content=get_prompt("responder.export_done")),
                HumanMessage(content=f"匯出檔：{title}"),
            ])
            text = getattr(resp, "text", None) or (resp.content if isinstance(resp.content, str) else "")
        return {"response": text, "messages": [AIMessage(content=text)]}
        # 匯出失敗（無 prev_form_data 等）→ 落入下方一般 RAG 路徑提供錯誤訊息

    # ── 靜態表單下載：短確認句 ─────────────────────────────
    if intent == "static_form_download" and form_explicit and matched_forms:
        names = "、".join(f"《{f['display_name']}》" for f in matched_forms)
        llm = get_llm("grader", temperature=0, streaming=True, stream_usage=True)
        response = await llm.ainvoke([
            SystemMessage(content=get_prompt("responder.static")),
            HumanMessage(content=f"找到：{names}"),
        ])
        text = getattr(response, "text", None) or (response.content if isinstance(response.content, str) else "")
        return {
            "response": text,
            "messages": [AIMessage(content=text)],
        }

    # ── 一般 QA / 動態表單生成 ─────────────────────────────
    llm = get_llm("default", temperature=0.6, streaming=True, stream_usage=True)

    prompt_messages = _build_messages(state)
    response = await llm.ainvoke(prompt_messages)

    # .text 是 LangChain 跨 provider 的統一文字 accessor：OpenAI 是純 str，
    # Gemini 3.x 是 list[block]（含 thought_signature），.text 都會回乾淨字串
    text = getattr(response, "text", None) or (response.content if isinstance(response.content, str) else "")
    return {
        "response": text,
        "messages": [AIMessage(content=text)],
    }

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


async def responder(state: GraphState) -> dict:
    """
    生成回覆。
    - 靜態表單明確請求：用短確認句，不做 RAG 生成
    - 一般 QA（含表單提示）：完整 RAG 生成
    streaming=True：配合 LangGraph astream_events，讓 chat endpoint 可逐 token 推送 SSE。
    """
    matched_forms = state.get("matched_forms", [])
    form_explicit = state.get("form_explicit", False)

    # 靜態表單明確請求：短確認句，跳過完整 RAG 系統提示
    if form_explicit and matched_forms:
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

    # 一般 QA / 動態表單生成
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

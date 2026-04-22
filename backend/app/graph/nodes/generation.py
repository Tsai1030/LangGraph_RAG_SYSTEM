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
你是一位專業的營造業內部知識助理，服務對象是公司內部員工。
根據以下參考文件，精確回答使用者的問題。

規則：
1. 優先使用參考文件中的資訊回答
2. 若文件中有相關表格或流程，以 Markdown 格式完整呈現
3. 圖片使用規則（重要）：
   - 引用圖片時**只能**用 Markdown 語法：![圖片說明](路徑)，路徑維持 /api/images/... 不變
   - **禁止**寫出「圖片路徑：」、「IMG-XXX」、圖片 ID 等純文字標籤
   - 當圖片能直接輔助說明時再引用，每次回答通常 1–3 張為宜，不需逐一列出所有圖片
4. 若本次已生成表單，在文字中說明「已為您生成表單，請查看下方預覽」
5. 若使用者問題不在文件範圍內，明確說明「文件中未記載此資訊」
6. 使用繁體中文回答，語氣專業但友善
7. 回答時**禁止**使用「依文件」、「文件中提到」、「文件明確指出」、「文件列出」、「根據文件」、「依據文件」等引用性措辭，直接陳述內容即可

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

    # 表單提示（若本次有生成表單）
    form_data = state.get("form_data")
    form_hint = ""
    if form_data:
        title = form_data.get("title", "表單")
        row_count = len(form_data.get("rows", []))
        form_hint = f"\n[本次已生成表單：「{title}」，共 {row_count} 筆資料]"

    system_content = _SYSTEM_PROMPT_TEMPLATE.format(
        summary_section=summary_section,
        context=state.get("context") or "（無相關文件）",
    ) + form_hint

    msgs: list[BaseMessage] = [SystemMessage(content=system_content)]

    # 加入對話歷史（只取 human/ai 訊息）
    for msg in state.get("messages", []):
        if isinstance(msg, (HumanMessage, AIMessage)):
            msgs.append(msg)

    return msgs


async def responder(state: GraphState) -> dict:
    """
    生成回覆。
    streaming=True：配合 LangGraph astream_events，讓 chat endpoint 可逐 token 推送 SSE。
    """
    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        temperature=0.3,
        streaming=True,
    )

    prompt_messages = _build_messages(state)
    response = await llm.ainvoke(prompt_messages)

    return {
        "response": response.content,
        "messages": [AIMessage(content=response.content)],
    }

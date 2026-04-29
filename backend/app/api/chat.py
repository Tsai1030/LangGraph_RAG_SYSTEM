"""
chat.py — SSE 聊天端點

流程：
1. 驗證 conversation 存在且屬於當前使用者
2. 儲存使用者訊息至 app.db
3. 設定對話標題（若首則訊息）
4. 從 app.db 載入既有摘要
5. 啟動 LangGraph graph.astream_events
6. 逐 token 推送 SSE text 事件
7. graph 完成後推送 sources / form / done 事件
8. 儲存 AI 回覆至 app.db
"""

from __future__ import annotations # python 未來性設定，型別註記處理會更彈性

import json # 把dict轉成json因為sse stream
from typing import AsyncGenerator  

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage # 建立langchain/langraph用的使用者訊息格式
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import AsyncSessionLocal, get_db
from app.models.user import User
from app.schemas.chat import ChatRequest
from app.services.conversation_service import (
    auto_set_title,
    get_summary,
    save_message,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(
    request: Request,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /api/chat/stream

    SSE 事件格式：
      {"type": "text",    "content": "..."}   # 逐 token 串流文字
      {"type": "sources", "data": [...]}       # 參考來源（一次性）
      {"type": "form",    "data": {...}}        # 表單 JSON（form_request 時）
      {"type": "error",   "content": "..."}    # 錯誤訊息
      {"type": "done"}                          # 串流結束
    """
    conversation_id = body.conversation_id
    user_id = str(current_user.id)

    # ── 1. 驗證對話所有權 ─────────────────────────────────────
    from app.services.conversation_service import get_conversation
    try:
        await get_conversation(db, conversation_id, user_id)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    # ── 2. 儲存使用者訊息 ─────────────────────────────────────
    await save_message(db, conversation_id, "user", body.message)

    # ── 3. 自動設定對話標題（首次訊息） ──────────────────────
    await auto_set_title(db, conversation_id, body.message)

    # ── 4. 載入既有摘要（app.db → graph state） ───────────────
    summary_record = await get_summary(db, conversation_id)
    summary_text = summary_record.summary if summary_record else None

    # ── 5. 取得 graph（由 lifespan 初始化於 app.state） ───────
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": conversation_id}}

    # 讀取最近一輪有生成過的 form_data（供多輪表單延續使用）
    # 若上一輪沒有 form（form_data=None），繼續往前找 prev_form_data，避免斷鏈
    prev_form_data = None
    try:
        prev_state = await graph.aget_state(config)
        if prev_state and prev_state.values:
            prev_form_data = (
                prev_state.values.get("form_data")
                or prev_state.values.get("prev_form_data")
            )
    except Exception:
        pass

    initial_state = {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "query": body.message,
        "messages": [HumanMessage(content=body.message)],  # add_messages 自動 append
        "retrieved_chunks": [],
        "context": "",
        "intent": "",
        "form_type": None,
        "response": "",
        "form_data": None,
        "sources": [],
        "is_compact_needed": False,
        "token_count": 0,
        "summary": summary_text,
        "need_retrieval": True,
        "retrieval_query": None,          # 每輪重置，避免上輪改寫結果污染本輪
        "retry_count": 0,                 # 每輪重置 CRAG 重試計數器
        "grader_reason": None,            # 每輪重置
        "grader_missing_information": None,
        "matched_forms": [],              # 靜態表單匹配結果
        "form_explicit": False,           # 是否為明確表單下載請求
        "is_form_continuation": False,    # 每輪重置，由 router 重新判斷
        "prev_form_data": prev_form_data, # 最近一輪有 form 的資料（多輪延續用）
    }

    # ── 6. SSE 事件生成器 ─────────────────────────────────────
    async def event_generator() -> AsyncGenerator[str, None]:
        assistant_response = ""
        had_error = False
        final_values: dict = {}  # 提前初始化，避免後續 NameError

        try:
            async for event in graph.astream_events(
                initial_state, config, version="v2"
            ):
                event_type = event.get("event", "")
                event_name = event.get("name", "")
                node_name = event.get("metadata", {}).get("langgraph_node", "")

                # form_structurer 開始 → 前端顯示「表單生成中」
                if event_type == "on_chain_start" and event_name == "form_structurer":
                    yield (
                        f"data: {json.dumps({'type': 'form_loading'})}\n\n"
                    )

                # 捕捉 responder 節點的串流 token
                if event_type == "on_chat_model_stream" and node_name == "responder":
                    chunk = event["data"].get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        assistant_response += chunk.content
                        yield (
                            f"data: {json.dumps({'type': 'text', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                        )

        except Exception as exc:
            had_error = True
            yield (
                f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
            )

        # ── 7. graph 完成後：讀取最終狀態，推送 sources / form ────
        if not had_error:
            try:
                final = await graph.aget_state(config)
                final_values = final.values if final else {}
            except Exception:
                pass  # 讀取失敗保留空 dict，不影響已串流文字

            sources = final_values.get("sources", [])
            if sources:
                yield (
                    f"data: {json.dumps({'type': 'sources', 'data': sources}, ensure_ascii=False)}\n\n"
                )

            form_data = final_values.get("form_data")
            if form_data:
                yield (
                    f"data: {json.dumps({'type': 'form', 'data': form_data}, ensure_ascii=False)}\n\n"
                )

            matched_forms = final_values.get("matched_forms", [])
            if matched_forms:
                yield (
                    f"data: {json.dumps({'type': 'form_files', 'data': matched_forms}, ensure_ascii=False)}\n\n"
                )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

        # ── 8. 儲存 AI 回覆至 app.db ──────────────────────────
        if assistant_response:
            try:
                async with AsyncSessionLocal() as save_db:
                    meta: dict = {}
                    if final_values.get("sources"):
                        meta["sources"] = final_values["sources"]
                    if final_values.get("form_data"):
                        meta["form_data"] = final_values["form_data"]
                    if final_values.get("matched_forms"):
                        meta["form_files"] = final_values["matched_forms"]
                    await save_message(
                        save_db,
                        conversation_id,
                        "assistant",
                        assistant_response,
                        metadata=meta or None,
                    )
            except Exception:
                pass  # 儲存失敗不影響已完成的串流

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

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

import asyncio
import json # 把dict轉成json因為sse stream
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
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
from app.services.image_store import resolve_image, save_upload

router = APIRouter(prefix="/chat", tags=["chat"])

_chat_semaphore = asyncio.Semaphore(20)

NODE_STEP_LABELS: dict[str, str] = {
    "vision_intake":        "Analyzing image…",
    "compact_check":        "Checking context…",
    "summarizer":           "Compressing history…",
    "unified_intent":       "Understanding intent…",
    "retriever":            "Searching knowledge base…",
    "context_builder":      "Building context…",
    "retrieval_grader":     "Evaluating relevance…",
    "query_rewriter":       "Refining search query…",
    "form_structurer":      "Structuring form…",
    "form_template_loader": "Loading form template…",
    "form_fill_collector":  "Collecting form fields…",
    "form_filler":          "Filling form…",
    "form_exporter":        "Exporting form…",
    "responder":            "Generating response…",
    "source_filter":        "Filtering sources…",
}


@router.post("/upload")
async def chat_upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """POST /api/chat/upload — 上傳一張圖片，回 {image_id, mime_type}。

    圖片存磁碟（settings.upload_dir/{user_id}/...）；送訊息時把回傳的
    image_id 放進 ChatRequest.image_ids。base64 不進 graph state。
    """
    try:
        return await save_upload(str(current_user.id), file)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@router.get("/image/{image_id}")
async def chat_image(
    image_id: str,
    current_user: User = Depends(get_current_user),
):
    """回傳使用者自己上傳的圖片（聊天泡泡縮圖用）。只允許存取自己上傳的圖。"""
    ref = resolve_image(str(current_user.id), image_id)
    if ref is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    return FileResponse(ref["path"], media_type=ref["mime"])


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

    # ── 1.5 系統容量檢查 ──────────────────────────────────────
    if _chat_semaphore.locked():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="系統目前繁忙，請稍後再試",
        )
    await _chat_semaphore.acquire()

    # ── 2. 儲存使用者訊息（含本輪上傳圖片，供泡泡縮圖；重整後仍可顯示）──
    user_meta = (
        {"images": [{"image_id": iid} for iid in body.image_ids]}
        if body.image_ids else None
    )
    await save_message(db, conversation_id, "user", body.message, metadata=user_meta)

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
    prev_image_refs: list = []
    prev_image_understanding = None
    try:
        prev_state = await graph.aget_state(config)
        if prev_state and prev_state.values:
            prev_form_data = (
                prev_state.values.get("form_data")
                or prev_state.values.get("prev_form_data")
            )
            # 多輪圖片延續：撈上一輪的圖片參照與解析（沿用「最近一張」直到有新圖）
            prev_image_refs = (
                prev_state.values.get("image_refs")
                or prev_state.values.get("prev_image_refs")
                or []
            )
            prev_image_understanding = (
                prev_state.values.get("image_understanding")
                or prev_state.values.get("prev_image_understanding")
            )
    except Exception:
        pass

    # ── 解析本輪上傳圖片（VLM）→ 只放輕量參照，base64 不進 state ──
    image_refs = [
        ref for iid in body.image_ids
        if (ref := resolve_image(user_id, iid)) is not None
    ]

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
        "image_refs": image_refs,         # VLM：本輪上傳的圖片參照（path/id）
        "image_understanding": None,      # vision_intake 產出
        "prev_image_refs": prev_image_refs,                 # 多輪延續：上一輪圖片（無新圖時沿用）
        "prev_image_understanding": prev_image_understanding,
    }

    # ── 6. SSE 事件生成器 ─────────────────────────────────────
    async def event_generator() -> AsyncGenerator[str, None]:
        assistant_response = ""
        had_error = False
        final_values: dict = {}  # 提前初始化，避免後續 NameError
        # 整輪所有 LLM call 的 usage 累計（unified_intent / grader / rewriter / responder /
        # source_filter / summarizer …）。寫進 assistant message 的 token_count 欄位。
        total_input_tokens = 0
        total_output_tokens = 0

        try:
            try:
                async for event in graph.astream_events(
                    initial_state, config, version="v2"
                ):
                    event_type = event.get("event", "")
                    event_name = event.get("name", "")
                    node_name = event.get("metadata", {}).get("langgraph_node", "")

                    # 每個 graph node 開始 → 推送 step 事件讓前端顯示進度
                    if event_type == "on_chain_start" and event_name in NODE_STEP_LABELS:
                        yield (
                            f"data: {json.dumps({'type': 'step', 'node': event_name, 'label': NODE_STEP_LABELS[event_name]})}\n\n"
                        )

                    # form_structurer 開始 → 推送 form_loading 讓前端顯示「Generating table…」
                    if event_type == "on_chain_start" and event_name == "form_structurer":
                        yield (
                            f"data: {json.dumps({'type': 'form_loading'})}\n\n"
                        )

                    # vision_intake 開始（且本輪有新上傳圖）→ 推 image_reading 顯示「讀取圖片中…」
                    if event_type == "on_chain_start" and event_name == "vision_intake" and image_refs:
                        yield (
                            f"data: {json.dumps({'type': 'image_reading'})}\n\n"
                        )

                    # 捕捉 responder 節點的串流 token
                    if event_type == "on_chat_model_stream" and node_name == "responder":
                        chunk = event["data"].get("chunk")
                        if chunk:
                            # Gemini 3.x 串流 chunk.content 是 list[dict]（含 thought signature
                            # blocks），OpenAI 是純 str。.text 是 LangChain 跨 provider 的
                            # 統一文字 accessor — 兩種都安全。
                            text = getattr(chunk, "text", None) or ""
                            if text:
                                assistant_response += text
                                yield (
                                    f"data: {json.dumps({'type': 'text', 'content': text}, ensure_ascii=False)}\n\n"
                                )

                    # 任何 LLM call 結束 → 累計 usage（含串流與非串流）
                    if event_type == "on_chat_model_end":
                        msg_out = event.get("data", {}).get("output")
                        usage = getattr(msg_out, "usage_metadata", None) or {}
                        total_input_tokens += usage.get("input_tokens", 0) or 0
                        total_output_tokens += usage.get("output_tokens", 0) or 0

            except Exception as exc:
                had_error = True
                # 細節記 log；前端只給通用英文錯誤訊息（避免內部訊息洩漏）
                import logging
                logging.getLogger("app.chat").exception(
                    "[chat_stream] graph error in conv=%s: %s",
                    conversation_id, exc,
                )
                yield (
                    f"data: {json.dumps({'type': 'error', 'content': 'Internal error'})}\n\n"
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

                # 動態表單：不再推送結構化 form 事件 — 表格內容已由 responder 寫進 markdown
                # 動態表單匯出：把 exported_form_file 用 form_files 形式推送
                # 靜態表單下載 / 靜態表填好：同既有 form_files 機制

                matched_forms = final_values.get("matched_forms", [])
                fill_session = final_values.get("form_fill_session") or {}
                exported = final_values.get("exported_form_file")
                intent = final_values.get("intent")

                if intent == "dynamic_form_export" and exported:
                    matched_forms = [exported]
                # 填表完成 → 把已填寫檔案以 form_files 形式推送（前端共用同一 UI 顯示下載按鈕）
                # **必須限定 intent=static_form_fill**：session 透過 checkpointer 跨輪持久化，
                # filled_token 會留在 state 裡，若無 intent gate 後續任何輪（qa / dynamic 等）
                # 都會誤推「(已填寫)」卡片。
                elif (
                    intent == "static_form_fill"
                    and fill_session.get("status") == "completed"
                    and fill_session.get("filled_token")
                ):
                    target_id = fill_session.get("target_form_id")
                    base_name = next(
                        (m["display_name"] for m in matched_forms if m.get("form_id") == target_id),
                        target_id or "已填寫表單",
                    )
                    matched_forms = [{
                        "form_id": f"{target_id}_filled",
                        "display_name": f"{base_name}（已填寫）",
                        "download_url": f"/api/forms/filled/{fill_session['filled_token']}",
                    }]
                # 填表收集中：抑制「空白模板」按鈕，避免使用者誤以為按下載就拿到填好的版本
                elif (
                    intent == "static_form_fill"
                    and fill_session.get("status") == "collecting"
                ):
                    matched_forms = []

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
                        # 注意：動態表單內容已寫進 assistant_response（markdown 表格），
                        # 不再額外存 form_data 到 metadata（前端不渲染 FormPreview 了）
                        if matched_forms:
                            # 此處 matched_forms 已是上方串流推送過的版本（filled / exported / 靜態）
                            meta["form_files"] = matched_forms
                        await save_message(
                            save_db,
                            conversation_id,
                            "assistant",
                            assistant_response,
                            metadata=meta or None,
                            input_tokens=total_input_tokens or None,
                            output_tokens=total_output_tokens or None,
                        )
                except Exception:
                    pass  # 儲存失敗不影響已完成的串流

        finally:
            _chat_semaphore.release()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

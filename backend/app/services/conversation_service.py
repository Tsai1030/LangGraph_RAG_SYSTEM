"""
conversation_service.py — 對話與訊息業務邏輯

功能：
- 對話 CRUD（建立、列表、取得、重命名、刪除）
- 訊息寫入（Phase 3 LangGraph 節點使用）
- 自動標題生成（第一則訊息前 30 字）
- 摘要更新（Phase 3 compact 機制使用）
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, update
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation
from app.models.message import Message
from app.models.summary import ConversationSummary


# ── 對話 CRUD ─────────────────────────────────────────────────

async def list_conversations(db: AsyncSession, user_id: str) -> list[tuple[Conversation, str | None]]:
    """
    取得使用者所有對話（未封存），依 updated_at 降序。
    Returns: list of (conversation, last_message_preview)
    """
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.is_archived == False)
        .order_by(desc(Conversation.updated_at))
    )
    conversations = result.scalars().all()

    out = []
    for conv in conversations:
        msg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        last_msg = msg_result.scalar_one_or_none()
        preview = last_msg.content[:80] if last_msg else None
        out.append((conv, preview))

    return out


async def create_conversation(
    db: AsyncSession,
    user_id: str,
    title: str | None = None,
) -> Conversation:
    """建立新對話"""
    conv = Conversation(user_id=user_id, title=title)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def get_conversation(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
) -> Conversation:
    """
    取得對話（eager load summary，避免 async lazy loading 問題）。
    Raises: HTTPException 404 if not found or not owned by user.
    """
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.summary))
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conv


async def rename_conversation(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
    new_title: str,
) -> Conversation:
    """重新命名對話標題"""
    conv = await get_conversation(db, conversation_id, user_id)
    conv.title = new_title
    await db.commit()
    await db.refresh(conv)
    return conv


async def delete_conversation(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
    *,
    checkpointer=None,
) -> None:
    """刪除對話。

    步驟：
      1. SQL CASCADE 刪 conversation / messages / summary（authoritative）
      2. best-effort 清理 generated_forms 內所屬的 .docx（失敗只記 log）
      3. best-effort 清理 LangGraph checkpoint thread state（若 checkpointer 提供）

    Args:
        checkpointer: AsyncSqliteSaver；由 API 端從 app.state 傳入。
                       為 None 時不清 checkpoint（測試 / fallback）。
    """
    import logging

    from app.services.form_fill_writer import delete_generated_for_conversation

    logger = logging.getLogger(__name__)

    # 先驗證所有權，避免越權刪除任何側邊資料
    conv = await get_conversation(db, conversation_id, user_id)

    await db.delete(conv)
    await db.commit()

    # 側邊資料清理（任何錯誤都不應該回滾 SQL；對話已刪掉）
    try:
        delete_generated_for_conversation(conversation_id)
    except Exception:
        logger.exception("[delete_conversation] generated_forms 清理失敗 conv=%s", conversation_id)

    # 上傳文件的 session 向量索引（delete_session 內部已 best-effort）
    from app.rag.session_store import delete_session
    delete_session(conversation_id)

    if checkpointer is not None:
        try:
            await checkpointer.adelete_thread(conversation_id)
            logger.info("[delete_conversation] cleared LangGraph thread %s", conversation_id)
        except Exception:
            logger.exception("[delete_conversation] checkpointer 清理失敗 conv=%s", conversation_id)


# ── 訊息寫入（Phase 3 LangGraph 節點使用）────────────────────

async def save_message(
    db: AsyncSession,
    conversation_id: str,
    role: str,
    content: str,
    metadata: dict | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> Message:
    """
    寫入一則訊息到資料庫。
    同時更新 conversation.updated_at。

    Args:
        role: 'user' | 'assistant' | 'system'
        metadata: sources、form_files 等結構化欄位
        input_tokens / output_tokens: 該則訊息整輪 LLM call 的 input / output token 累計。
                                       user 訊息預設不填，舊資料保持 NULL。
                                       token_count 自動填為 (input + output)。
    """
    total = None
    if input_tokens is not None or output_tokens is not None:
        total = (input_tokens or 0) + (output_tokens or 0)

    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        meta=metadata,
        token_count=total,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(msg)

    # 更新 conversation.updated_at（讓列表排序正確）
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=datetime.now(timezone.utc))
    )

    await db.commit()
    await db.refresh(msg)
    return msg


async def auto_set_title(
    db: AsyncSession,
    conversation_id: str,
    first_message: str,
) -> None:
    """
    若對話標題為空，自動設定為第一則訊息前 30 字。
    Phase 3 在儲存第一則 user 訊息後呼叫。
    """
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if conv and not conv.title:
        conv.title = first_message[:30]
        await db.commit()


async def get_messages(
    db: AsyncSession,
    conversation_id: str,
) -> list[Message]:
    """取得對話的所有訊息（依 created_at 升序）"""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


async def delete_messages_from(
    db: AsyncSession,
    conversation_id: str,
    from_message_id: str,
    *,
    checkpointer=None,
) -> None:
    """從指定訊息（含）起，刪除其後所有訊息，並清掉 LangGraph thread state。

    Why: retry 流程要把「要重答的那則 user 訊息」與其後所有訊息抹掉，再讓
    /chat/stream 重跑一次。LangGraph checkpointer 內 messages 是用 add_messages
    reducer，殘留會導致下一次 graph 執行時訊息列表被重複 append，所以一併清掉。
    """
    import logging
    from sqlalchemy import delete as sql_delete

    logger = logging.getLogger(__name__)

    anchor_result = await db.execute(
        select(Message).where(
            Message.id == from_message_id,
            Message.conversation_id == conversation_id,
        )
    )
    anchor = anchor_result.scalar_one_or_none()
    if not anchor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found in conversation",
        )

    await db.execute(
        sql_delete(Message).where(
            Message.conversation_id == conversation_id,
            Message.created_at >= anchor.created_at,
        )
    )
    await db.commit()

    if checkpointer is not None:
        try:
            await checkpointer.adelete_thread(conversation_id)
        except Exception:
            logger.exception(
                "[delete_messages_from] checkpointer 清理失敗 conv=%s", conversation_id
            )


# ── 摘要（Phase 3 compact 機制使用）──────────────────────────

async def upsert_summary(
    db: AsyncSession,
    conversation_id: str,
    summary_text: str,
    up_to_message_id: str,
    summarized_message_count: int,
) -> ConversationSummary:
    """
    新增或更新對話摘要（conversation_summaries 是 1:1 關係）。
    Phase 3 summarizer 節點呼叫。
    """
    result = await db.execute(
        select(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation_id
        )
    )
    summary = result.scalar_one_or_none()

    if summary:
        summary.summary = summary_text
        summary.summarized_up_to_message_id = up_to_message_id
        summary.summarized_message_count = summarized_message_count
        summary.updated_at = datetime.now(timezone.utc)
    else:
        summary = ConversationSummary(
            conversation_id=conversation_id,
            summary=summary_text,
            summarized_up_to_message_id=up_to_message_id,
            summarized_message_count=summarized_message_count,
        )
        db.add(summary)

    await db.commit()
    await db.refresh(summary)
    return summary


async def get_summary(
    db: AsyncSession,
    conversation_id: str,
) -> ConversationSummary | None:
    """取得對話摘要（若有）"""
    result = await db.execute(
        select(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation_id
        )
    )
    return result.scalar_one_or_none()

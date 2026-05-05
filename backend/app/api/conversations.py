from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
    MessageOut,
)
from app.services.conversation_service import (
    list_conversations,
    create_conversation,
    get_conversation,
    rename_conversation,
    delete_conversation,
    delete_messages_from,
    get_messages,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations_endpoint(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items = await list_conversations(db, current_user.id)
    out = []
    for conv, preview in items:
        item = ConversationOut.model_validate(conv)
        item.last_message_preview = preview
        out.append(item)
    return out


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation_endpoint(
    body: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await create_conversation(db, current_user.id, body.title)
    return ConversationOut.model_validate(conv)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation_endpoint(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_conversation(db, conversation_id, current_user.id)
    messages = await get_messages(db, conversation_id)
    summary_text = conv.summary.summary if conv.summary else None

    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        is_archived=conv.is_archived,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[MessageOut.model_validate(m) for m in messages],
        summary=summary_text,
    )


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation_endpoint(
    conversation_id: str,
    body: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await rename_conversation(db, conversation_id, current_user.id, body.title)
    return ConversationOut.model_validate(conv)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation_endpoint(
    request: Request,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    checkpointer = getattr(request.app.state, "checkpointer", None)
    await delete_conversation(
        db,
        conversation_id,
        current_user.id,
        checkpointer=checkpointer,
    )


@router.delete(
    "/{conversation_id}/messages/{message_id}/onward",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_messages_from_endpoint(
    request: Request,
    conversation_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry 用：從指定訊息起截斷對話，並清 LangGraph thread state。"""
    await get_conversation(db, conversation_id, current_user.id)
    checkpointer = getattr(request.app.state, "checkpointer", None)
    await delete_messages_from(
        db,
        conversation_id,
        message_id,
        checkpointer=checkpointer,
    )

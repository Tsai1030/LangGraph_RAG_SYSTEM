from datetime import datetime

from pydantic import BaseModel


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationUpdate(BaseModel):
    title: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    meta: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: str
    title: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    last_message_preview: str | None = None

    model_config = {"from_attributes": True}


class ConversationDetail(BaseModel):
    id: str
    title: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]
    summary: str | None = None

    model_config = {"from_attributes": True}

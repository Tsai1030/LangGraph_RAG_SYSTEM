from datetime import datetime

from pydantic import BaseModel


class AdminUserOut(BaseModel):
    id: str
    email: str
    display_name: str | None
    role: str
    is_active: bool
    search_enabled: bool = False
    created_at: datetime
    updated_at: datetime
    conversation_count: int = 0
    last_active_at: datetime | None = None

    model_config = {"from_attributes": True}


class AdminUserListOut(BaseModel):
    items: list[AdminUserOut]
    total: int
    limit: int
    offset: int


class ToggleActiveRequest(BaseModel):
    is_active: bool


class ToggleSearchPermissionRequest(BaseModel):
    search_enabled: bool


class AdminMessageOut(BaseModel):
    id: str
    role: str
    content: str
    token_count: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminConversationOut(BaseModel):
    id: str
    user_id: str
    user_email: str | None = None
    title: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class AdminConversationDetail(AdminConversationOut):
    messages: list[AdminMessageOut] = []


class StatsBreakdown(BaseModel):
    total: int = 0
    today: int = 0
    this_week: int = 0


class AdminStatsOut(BaseModel):
    users: dict[str, int]
    conversations: StatsBreakdown
    messages: StatsBreakdown
    tokens: dict[str, int]
    cost_estimate_usd: dict[str, float]
    note: str = ""


class VectorCollectionInfo(BaseModel):
    name: str
    document_count: int
    sample_files: list[str] = []  # 抽樣前 20 個 unique source 檔名


class AdminVectorInfo(BaseModel):
    active_version: str
    resolved_path: str
    collections: list[VectorCollectionInfo]


class AdminMessageBriefOut(BaseModel):
    """admin reset password 回傳訊息"""
    message: str


class AdminTimeSeriesPoint(BaseModel):
    """每日彙總資料點。date 為 UTC 日期 (YYYY-MM-DD)。"""
    date: str
    messages: int = 0
    conversations: int = 0
    tokens: int = 0


class AdminTimeSeriesOut(BaseModel):
    days: int
    points: list[AdminTimeSeriesPoint]

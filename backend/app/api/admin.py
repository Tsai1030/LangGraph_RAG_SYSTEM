"""
admin.py — 管理員 API（/api/admin/*）

所有路由都用 get_current_admin 守，role != "admin" → 403。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.dependencies import get_current_admin
from app.core.security import create_password_reset_token
from app.database import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.schemas.admin import (
    AdminConversationDetail,
    AdminConversationOut,
    AdminMessageBriefOut,
    AdminMessageOut,
    AdminStatsOut,
    AdminTimeSeriesOut,
    AdminTimeSeriesPoint,
    AdminUserListOut,
    AdminUserOut,
    AdminVectorInfo,
    StatsBreakdown,
    ToggleActiveRequest,
    ToggleSearchPermissionRequest,
    VectorCollectionInfo,
)
from app.services.email_service import send_password_reset_email

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_admin)])
logger = logging.getLogger("app.admin")

# gpt-5.4 標準價（per 1M tokens, USD）。input 與 output 單價差 6 倍，必須分開計算。
# 來源：https://openai.com/api/pricing/
# 不含 cache hit 折扣（cached input $0.25/1M）與 long-context 加價，亦不含 embedding 費用。
_USD_PER_1M_INPUT = 2.50
_USD_PER_1M_OUTPUT = 15.00


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return round(
        input_tokens / 1_000_000 * _USD_PER_1M_INPUT
        + output_tokens / 1_000_000 * _USD_PER_1M_OUTPUT,
        4,
    )


# ─────────────────────────── Users ───────────────────────────

@router.get("/users", response_model=AdminUserListOut)
async def list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, description="email 或 display_name 模糊比對"),
    db: AsyncSession = Depends(get_db),
):
    base_q = select(User)
    if search:
        like = f"%{search}%"
        base_q = base_q.where((User.email.ilike(like)) | (User.display_name.ilike(like)))

    total_q = select(func.count()).select_from(base_q.subquery())
    total = (await db.execute(total_q)).scalar_one()

    rows = (
        await db.execute(
            base_q.order_by(User.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()

    if not rows:
        return AdminUserListOut(items=[], total=total, limit=limit, offset=offset)

    user_ids = [u.id for u in rows]

    # 對話數
    conv_counts = dict(
        (await db.execute(
            select(Conversation.user_id, func.count(Conversation.id))
            .where(Conversation.user_id.in_(user_ids))
            .group_by(Conversation.user_id)
        )).all()
    )

    # 最近一次發訊息時間（透過 join messages → conversations）
    last_active = dict(
        (await db.execute(
            select(Conversation.user_id, func.max(Message.created_at))
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Conversation.user_id.in_(user_ids))
            .group_by(Conversation.user_id)
        )).all()
    )

    items = [
        AdminUserOut(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=u.role,
            is_active=u.is_active,
            search_enabled=u.search_enabled,
            created_at=u.created_at,
            updated_at=u.updated_at,
            conversation_count=conv_counts.get(u.id, 0),
            last_active_at=last_active.get(u.id),
        )
        for u in rows
    ]
    return AdminUserListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/users/{user_id}", response_model=AdminUserOut)
async def get_user(user_id: str, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    conv_count = (await db.execute(
        select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
    )).scalar_one()

    last_active = (await db.execute(
        select(func.max(Message.created_at))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id)
    )).scalar_one()

    return AdminUserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        search_enabled=user.search_enabled,
        created_at=user.created_at,
        updated_at=user.updated_at,
        conversation_count=conv_count,
        last_active_at=last_active,
    )


@router.patch("/users/{user_id}/active", response_model=AdminUserOut)
async def toggle_user_active(
    user_id: str,
    body: ToggleActiveRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot disable your own account")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = body.is_active
    if not body.is_active:
        # 停用時 bump tv 把舊 token 全部踢掉
        user.token_version = (user.token_version or 0) + 1
    await db.commit()
    await db.refresh(user)

    return AdminUserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        search_enabled=user.search_enabled,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.patch("/users/{user_id}/search-permission", response_model=AdminUserOut)
async def toggle_user_search_permission(
    user_id: str,
    body: ToggleSearchPermissionRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """切換使用者的鋼筋盤價助理使用權限。

    跟 is_active 不同——admin 可以改自己（最差只是失去 search 功能，不會鎖死登入），
    也不 bump token_version（搜尋權限是即時 DB 讀取的，不存在 token 內）。
    """
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.search_enabled = body.search_enabled
    await db.commit()
    await db.refresh(user)

    return AdminUserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        search_enabled=user.search_enabled,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.post("/users/{user_id}/reset-password", response_model=AdminMessageBriefOut)
async def admin_reset_password(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """寄重設信給該 user。回傳 200，不論寄信成功失敗（避免洩露 user 狀態）。"""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token = create_password_reset_token(str(user.id), token_version=user.token_version)
    reset_link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={token}"
    try:
        await send_password_reset_email(user.email, reset_link, user.display_name)
        return AdminMessageBriefOut(message=f"Reset email sent to {user.email}")
    except Exception as e:
        logger.error("admin reset email failed for %s: %s", user.email, e)
        raise HTTPException(status_code=500, detail="Failed to send reset email")


# ───────────────────────── Conversations ─────────────────────────

@router.get("/users/{user_id}/conversations", response_model=list[AdminConversationOut])
async def list_user_conversations(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rows = (await db.execute(
        select(
            Conversation,
            func.count(Message.id).label("msg_count"),
        )
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
    )).all()

    return [
        AdminConversationOut(
            id=c.id,
            user_id=c.user_id,
            user_email=user.email,
            title=c.title,
            is_archived=c.is_archived,
            created_at=c.created_at,
            updated_at=c.updated_at,
            message_count=msg_count,
        )
        for c, msg_count in rows
    ]


@router.get("/conversations/{conversation_id}", response_model=AdminConversationDetail)
async def get_any_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_email = (await db.execute(
        select(User.email).where(User.id == conv.user_id)
    )).scalar_one_or_none()

    messages = (await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )).scalars().all()

    return AdminConversationDetail(
        id=conv.id,
        user_id=conv.user_id,
        user_email=user_email,
        title=conv.title,
        is_archived=conv.is_archived,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=len(messages),
        messages=[AdminMessageOut.model_validate(m) for m in messages],
    )


# ───────────────────────────── Stats ─────────────────────────────

@router.get("/stats", response_model=AdminStatsOut)
async def get_stats(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    async def count_where(model_cls, *clauses) -> int:
        q = select(func.count()).select_from(model_cls)
        for c in clauses:
            q = q.where(c)
        return (await db.execute(q)).scalar_one()

    # Users
    total_users = await count_where(User)
    active_users = await count_where(User, User.is_active == True)  # noqa: E712
    admin_users = await count_where(User, User.role == "admin")

    # Conversations
    total_conv = await count_where(Conversation)
    today_conv = await count_where(Conversation, Conversation.created_at >= today_start)
    week_conv = await count_where(Conversation, Conversation.created_at >= week_ago)

    # Messages
    total_msg = await count_where(Message)
    today_msg = await count_where(Message, Message.created_at >= today_start)
    week_msg = await count_where(Message, Message.created_at >= week_ago)

    # Tokens — 拆 input / output 分別 sum（input 與 output 單價差 6 倍）
    async def _sum_tokens(*clauses) -> tuple[int, int, int]:
        q = select(
            func.coalesce(func.sum(Message.input_tokens), 0),
            func.coalesce(func.sum(Message.output_tokens), 0),
            func.coalesce(func.sum(Message.token_count), 0),
        )
        for c in clauses:
            q = q.where(c)
        row = (await db.execute(q)).one()
        return int(row[0]), int(row[1]), int(row[2])

    in_total, out_total, total_tokens = await _sum_tokens()
    in_today, out_today, today_tokens = await _sum_tokens(Message.created_at >= today_start)

    cost_total = _estimate_cost(in_total, out_total)
    cost_today = _estimate_cost(in_today, out_today)

    return AdminStatsOut(
        users={"total": total_users, "active": active_users, "admin": admin_users},
        conversations=StatsBreakdown(total=total_conv, today=today_conv, this_week=week_conv),
        messages=StatsBreakdown(total=total_msg, today=today_msg, this_week=week_msg),
        tokens={"total": total_tokens, "today": today_tokens},
        cost_estimate_usd={"total": cost_total, "today": cost_today},
        note=(
            f"成本估算採 gpt-5.4 標準價：input ${_USD_PER_1M_INPUT}/1M、output ${_USD_PER_1M_OUTPUT}/1M。"
            "不含 cache hit 折扣、long-context 加價、embedding API 費用。"
            "舊訊息（schema 升級前）token 欄位為 NULL，不計入。"
        ),
    )


@router.get("/stats/timeseries", response_model=AdminTimeSeriesOut)
async def get_stats_timeseries(
    days: int = Query(30, ge=1, le=365, description="回看天數（含今日）"),
    db: AsyncSession = Depends(get_db),
):
    """每日彙總（messages / conversations / tokens），以 UTC 日為粒度。

    缺資料的日期會補 0，方便前端直接畫折線圖。
    """
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    msg_rows = (await db.execute(
        select(
            func.date(Message.created_at).label("d"),
            func.count(Message.id),
            func.coalesce(func.sum(Message.token_count), 0),
        )
        .where(Message.created_at >= start)
        .group_by(func.date(Message.created_at))
    )).all()
    msg_map = {str(r[0]): (int(r[1]), int(r[2])) for r in msg_rows}

    conv_rows = (await db.execute(
        select(
            func.date(Conversation.created_at).label("d"),
            func.count(Conversation.id),
        )
        .where(Conversation.created_at >= start)
        .group_by(func.date(Conversation.created_at))
    )).all()
    conv_map = {str(r[0]): int(r[1]) for r in conv_rows}

    points: list[AdminTimeSeriesPoint] = []
    for i in range(days):
        d = (start + timedelta(days=i)).date().isoformat()
        m_count, m_tokens = msg_map.get(d, (0, 0))
        points.append(AdminTimeSeriesPoint(
            date=d,
            messages=m_count,
            conversations=conv_map.get(d, 0),
            tokens=m_tokens,
        ))

    return AdminTimeSeriesOut(days=days, points=points)


# ───────────────────────────── Vector ─────────────────────────────

@router.get("/vector/info", response_model=AdminVectorInfo)
async def get_vector_info():
    """G v1：唯讀檢視當前 Chroma 設定與 collection 概況。"""
    import asyncio
    from pathlib import Path

    import chromadb
    from chromadb.config import Settings as ChromaSettings

    if settings.chroma_active_version:
        resolved = str(Path(settings.chroma_versions_path) / settings.chroma_active_version)
    else:
        resolved = settings.chroma_persist_path

    def _read_collections() -> list[VectorCollectionInfo]:
        client = chromadb.PersistentClient(
            path=resolved,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        out: list[VectorCollectionInfo] = []
        for col in client.list_collections():
            try:
                count = col.count()
                # 抽樣前 50 筆找 unique source 檔名
                sample = col.get(limit=50, include=["metadatas"])
                files = set()
                for meta in sample.get("metadatas") or []:
                    if not meta:
                        continue
                    for key in ("source", "file", "filename", "doc_id"):
                        if v := meta.get(key):
                            files.add(str(v))
                            break
                out.append(VectorCollectionInfo(
                    name=col.name,
                    document_count=count,
                    sample_files=sorted(files)[:20],
                ))
            except Exception as e:
                logger.warning("read collection %s failed: %s", col.name, e)
                out.append(VectorCollectionInfo(name=col.name, document_count=-1))
        return out

    collections = await asyncio.to_thread(_read_collections)

    return AdminVectorInfo(
        active_version=settings.chroma_active_version or "(default)",
        resolved_path=resolved,
        collections=collections,
    )


@router.post("/vector/refresh-bm25")
async def refresh_bm25():
    """重建 BM25 索引（KB 離線更新後免重啟 hybrid 檢索就吃到新文件）。

    注意：讀的是「當前已開啟」的 Chroma collection；換 CHROMA_ACTIVE_VERSION
    仍需重啟（vector_store client 是 process 級快取）。router 層已掛
    get_current_admin，僅 admin 可呼叫。
    """
    import time as _time

    from app.rag.retriever import rebuild_bm25

    t0 = _time.perf_counter()
    count = await rebuild_bm25()
    elapsed_ms = int((_time.perf_counter() - t0) * 1000)
    logger.info("[vector] BM25 rebuilt: %d docs in %d ms", count, elapsed_ms)
    return {"document_count": count, "elapsed_ms": elapsed_ms}

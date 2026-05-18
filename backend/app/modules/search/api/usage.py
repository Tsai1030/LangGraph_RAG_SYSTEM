"""SEARCH usage stats — admin-only view of who ran how many generations.

Cross-DB read by design:
    GenerationRun lives in search.db with started_by = RAG user UUID.
    To show emails / display names we look those up from app.db.

    We cannot SQL-JOIN across attached DBs in async SQLAlchemy without
    setting up an ATTACH DATABASE side-channel that we'd have to
    maintain. Cheaper to issue two queries and merge in Python — the
    user count is tiny (single digits to maybe low double digits).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_admin
from app.database import get_db
from app.models.user import User
from app.search_database import get_search_db

from ..storage.models import GenerationRun
from .schemas import UsageAggregateRow

router = APIRouter(prefix="/admin/search-usage", tags=["search-admin-usage"])


@router.get("", response_model=list[UsageAggregateRow])
async def list_usage(
    _admin: User = Depends(get_current_admin),
    search_db: AsyncSession = Depends(get_search_db),
    app_db: AsyncSession = Depends(get_db),
) -> list[UsageAggregateRow]:
    """Per-user counts pulled from generation_runs, joined with RAG users.

    Cheap to compute live — the run count is small. Promote to a
    materialised view only if generation_runs grows past ~100k rows.
    """
    # 1) aggregate in search.db, keyed by started_by (UUID or NULL).
    stmt = (
        select(
            GenerationRun.started_by,
            func.count(GenerationRun.id).label("total"),
            func.sum(
                case((GenerationRun.status == "success", 1), else_=0)
            ).label("success"),
            func.sum(
                case((GenerationRun.status == "failed", 1), else_=0)
            ).label("failed"),
            func.sum(
                case((GenerationRun.status == "partial", 1), else_=0)
            ).label("partial"),
            func.max(GenerationRun.started_at).label("last_run"),
        )
        .group_by(GenerationRun.started_by)
        .order_by(func.max(GenerationRun.started_at).desc())
    )
    rows = (await search_db.execute(stmt)).all()

    # 2) one shot lookup of all referenced UUIDs in RAG app.db.
    user_ids = [r[0] for r in rows if r[0] is not None]
    if user_ids:
        user_rows = (
            await app_db.execute(
                select(User.id, User.email, User.display_name)
                .where(User.id.in_(user_ids))
            )
        ).all()
        user_map: dict[str, tuple[str, str | None]] = {
            uid: (email, display) for uid, email, display in user_rows
        }
    else:
        user_map = {}

    out: list[UsageAggregateRow] = []
    for started_by, total, success, failed, partial, last_run in rows:
        email = display_name = None
        if started_by is not None:
            email, display_name = user_map.get(started_by, (None, None))
        out.append(UsageAggregateRow(
            user_id=started_by,
            email=email,
            display_name=display_name,
            runs_total=int(total or 0),
            runs_success=int(success or 0),
            runs_failed=int(failed or 0),
            runs_partial=int(partial or 0),
            last_run_at=last_run if isinstance(last_run, datetime) else None,
        ))
    return out

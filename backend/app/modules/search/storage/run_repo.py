"""GenerationRun lifecycle queries (async).

A "run" is one execution of the LangGraph from /api/search/generation/run.
States: 'running' -> 'success' | 'partial' | 'failed'.

The API layer creates a row, fires asyncio.create_task, and returns
the run_id immediately. The background task updates the row through
this repo as it progresses.

reap_stranded() exists because PM2 / dev reload kills background
tasks mid-run; on next startup we mark any 'running' rows as 'failed'
so the frontend stops polling forever.
"""
from __future__ import annotations

from datetime import date as date_t
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GenerationRun


async def create(
    db: AsyncSession,
    *,
    meeting_date: date_t,
    started_by: str | None,
) -> GenerationRun:
    """Insert a new run in 'running' state. Caller spawns the task."""
    row = GenerationRun(
        meeting_date=meeting_date,
        started_by=started_by,
        status="running",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get(db: AsyncSession, run_id: int) -> GenerationRun | None:
    return (
        await db.execute(
            select(GenerationRun).where(GenerationRun.id == run_id)
        )
    ).scalar_one_or_none()


async def list_by_user(
    db: AsyncSession, user_id: str, limit: int = 50
) -> list[GenerationRun]:
    return (
        await db.execute(
            select(GenerationRun)
            .where(GenerationRun.started_by == user_id)
            .order_by(GenerationRun.started_at.desc())
            .limit(limit)
        )
    ).scalars().all()


async def list_all(db: AsyncSession, limit: int = 100) -> list[GenerationRun]:
    """Admin usage view — newest first."""
    return (
        await db.execute(
            select(GenerationRun)
            .order_by(GenerationRun.started_at.desc())
            .limit(limit)
        )
    ).scalars().all()


async def update_status(
    db: AsyncSession,
    run_id: int,
    *,
    status: str,
    output_path: str | None = None,
    notes: str | None = None,
    result_json: str | None = None,
    finished_at: datetime | None = None,
) -> None:
    """Update mutable fields. Only writes columns the caller set explicitly."""
    row = await get(db, run_id)
    if row is None:
        return
    row.status = status
    if output_path is not None:
        row.output_path = output_path
    if notes is not None:
        row.notes = notes
    if result_json is not None:
        row.result_json = result_json
    if finished_at is not None:
        row.finished_at = finished_at
    db.add(row)
    await db.commit()


async def reap_stranded(db: AsyncSession) -> int:
    """On startup, sweep 'running' rows to 'failed' with an audit note.

    Returns the count of rows reaped. Idempotent — re-running is a no-op
    if nothing is stuck.
    """
    now = datetime.utcnow()
    stmt = (
        update(GenerationRun)
        .where(GenerationRun.status == "running")
        .values(
            status="failed",
            finished_at=now,
            notes=GenerationRun.notes + " [reaped on startup]",
        )
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or 0

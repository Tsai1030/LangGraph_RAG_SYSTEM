"""SEARCH SQLAlchemy models on SearchBase (writes search.db).

Translated 1:1 from SEARCH's original SQLModel definitions. Column
names, lengths, indexes, default values MUST match what
scripts/migrate_search_db.py produces (verified by .schema diff at
the end of Phase 2). Anything that drifts will fail to round-trip
existing rows.

Three actor columns are nullable (started_by, csc_*.updated_by) —
this is a deliberate consequence of dropping SEARCH's local users
table. RAG owns identity now; legacy/synthetic actors become NULL.

Hard rule: NO `relationship()` here. The repos eager-load with
`selectinload` when joins are needed; lazy load on an async session
raises MissingGreenlet at runtime. Adding a relation later without
also adding the eager-load is a footgun that won't surface until a
specific code path runs.
"""
from __future__ import annotations

from datetime import date as date_t
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.search_database import SearchBase


def _utcnow() -> datetime:
    """SQLAlchemy `default=` callable. Naïve UTC to match the existing
    rows in search.db, which were written by SQLModel's default_factory
    that also used datetime.utcnow() (no tz). Switching to tz-aware
    here would break the column type in SQLite's flexible storage."""
    return datetime.utcnow()


class PriceHistory(SearchBase):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    value_date: Mapped[date_t] = mapped_column(index=True, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_text: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_url: Mapped[str] = mapped_column(String, nullable=False, default="")
    confidence: Mapped[str] = mapped_column(String(8), nullable=False, default="high")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    fetched_by: Mapped[str] = mapped_column(String(64), nullable=False)


class CscPriceState(SearchBase):
    """One row per (group, slot_index) — current state of 中鋼 prices."""

    __tablename__ = "csc_price_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 'group' is a SQL reserved word — quoted in DDL but Python attr is fine.
    group: Mapped[str] = mapped_column("group", String(16), index=True, nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    prev_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    change_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    # Nullable: legacy rows from SEARCH ('seed_csc' script) were NULLed by
    # migrate_search_db.py. New writes from RAG store UUID strings.
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CscAnnouncementMeta(SearchBase):
    """Header metadata above 中鋼 tables in 八.1 / 八.2."""

    __tablename__ = "csc_announcement_meta"

    group: Mapped[str] = mapped_column("group", String(16), primary_key=True)
    period_label: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    announce_date: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class GenerationRun(SearchBase):
    __tablename__ = "generation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_date: Mapped[date_t] = mapped_column(nullable=False)
    # Nullable: legacy SEARCH runs (started_by = 'admin' string) were
    # rewritten to UUIDs by the migration; unmappable ones became NULL.
    # New runs from RAG always store str(current_user.id).
    started_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    # 'running' | 'success' | 'partial' | 'failed'
    output_path: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str] = mapped_column(String, nullable=False, default="")
    # JSON blob — slot_values + confidence + serialised FetchResult list.
    # Populated by the background task on completion so /{id}/status can
    # return the full result without re-running the graph.
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="")


__all__ = ["PriceHistory", "CscPriceState", "CscAnnouncementMeta", "GenerationRun"]

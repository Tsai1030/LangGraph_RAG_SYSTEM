"""Price history queries (async, on SearchAsyncSessionLocal).

The orchestrator's persist node calls upsert_price for each fetched
slot; the narrate node calls list_recent / get_latest_before to fill
section 七 (recent prices table).

Conventions:
    - Each function takes `db: AsyncSession`. The caller owns
      transactions — these helpers commit only when the operation
      semantically *is* the transaction (upsert_price). Read helpers
      never commit.
    - Returning ORM objects only inside an open session. For the
      orchestrator we return plain values / FetchResult to avoid
      detached-attribute access bugs later.
"""
from __future__ import annotations

from datetime import date as date_t
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.search.core.slot_schema import SLOTS_BY_KEY
from app.modules.search.sources.base import FetchResult

from .models import PriceHistory


async def upsert_price(
    db: AsyncSession,
    result: FetchResult,
    value_date: date_t,
    fetched_by: str | None,
) -> None:
    """Insert-or-update one price row, keyed by (slot_key, value_date, source).

    `source` is derived from the slot definition — the single source of
    truth lives in slot_schema, not the FetchResult, so consumers can't
    accidentally write the wrong source name and create dupes.
    """
    slot_def = SLOTS_BY_KEY.get(result.slot_key)
    source_name = slot_def.source if slot_def and slot_def.source else "unknown"

    existing = (
        await db.execute(
            select(PriceHistory).where(
                PriceHistory.slot_key == result.slot_key,
                PriceHistory.value_date == value_date,
                PriceHistory.source == source_name,
            )
        )
    ).scalar_one_or_none()

    row = existing or PriceHistory(
        slot_key=result.slot_key,
        value_date=value_date,
        source=source_name,
        fetched_by=fetched_by or "",
    )
    row.value = result.value
    row.unit = result.unit
    row.raw_text = result.raw_text
    row.source_url = result.source_url
    row.confidence = result.confidence
    row.fetched_at = datetime.utcnow()
    row.fetched_by = fetched_by or ""
    db.add(row)
    await db.commit()


async def get_latest_before(
    db: AsyncSession,
    slot_key: str,
    before_date: date_t,
) -> FetchResult | None:
    row = (
        await db.execute(
            select(PriceHistory)
            .where(
                PriceHistory.slot_key == slot_key,
                PriceHistory.value_date < before_date,
            )
            .order_by(PriceHistory.value_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if row is None:
        return None
    return FetchResult(
        slot_key=row.slot_key,
        value=row.value,
        unit=row.unit or "",
        raw_text=row.raw_text,
        source_url=row.source_url,
        confidence=row.confidence,  # type: ignore[arg-type]
        fetched_at=row.fetched_at.isoformat(),
    )


async def list_recent(
    db: AsyncSession,
    slot_key: str,
    before_or_on: date_t,
    count: int = 7,
) -> list[tuple[date_t, float | None]]:
    """Return up to `count` most recent (date, value) pairs <= before_or_on,
    ordered ascending by date (oldest first). Used to fill section 七."""
    rows = (
        await db.execute(
            select(PriceHistory)
            .where(
                PriceHistory.slot_key == slot_key,
                PriceHistory.value_date <= before_or_on,
            )
            .order_by(PriceHistory.value_date.desc())
            .limit(count)
        )
    ).scalars().all()
    pairs = [(r.value_date, r.value) for r in rows]
    return list(reversed(pairs))


async def list_history(
    db: AsyncSession,
    slot_key: str,
    limit: int = 20,
) -> list[FetchResult]:
    rows = (
        await db.execute(
            select(PriceHistory)
            .where(PriceHistory.slot_key == slot_key)
            .order_by(PriceHistory.value_date.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        FetchResult(
            slot_key=r.slot_key,
            value=r.value,
            unit=r.unit or "",
            raw_text=r.raw_text,
            source_url=r.source_url,
            confidence=r.confidence,  # type: ignore[arg-type]
            fetched_at=r.fetched_at.isoformat(),
        )
        for r in rows
    ]

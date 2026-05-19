"""CRUD for 中鋼盤價 state (async).

Mirrors SEARCH's csc_store.py API but in async style. Two-tier:
    CscPriceState        — 26 rows (10 monthly + 16 quarterly) of prices
    CscAnnouncementMeta  — 2 rows (one per group) of period_label /
                           announce_date displayed in section headers.

Both treated as state, not history — admin writes overwrite in place.
"""
from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.search.core.csc_products import MONTHLY_PRODUCTS, QUARTERLY_PRODUCTS

from .models import CscAnnouncementMeta, CscPriceState


class CscRowDto(TypedDict):
    slot_index: int
    product_name: str
    prev_price: int
    change_amount: int
    new_price: int   # computed = prev + change


class CscGroupSnapshot(TypedDict):
    group: str
    period_label: str
    announce_date: str
    rows: list[CscRowDto]


def _products_for(group: str) -> list[str]:
    return MONTHLY_PRODUCTS if group == "monthly" else QUARTERLY_PRODUCTS


async def read_snapshot(db: AsyncSession, group: str) -> CscGroupSnapshot:
    """Return current rows + meta for one group, ordered by slot_index.

    Missing rows are filled in with zeros so the response shape is
    always len(products) regardless of seed state.
    """
    meta = await db.get(CscAnnouncementMeta, group)
    rows_db = (
        await db.execute(
            select(CscPriceState)
            .where(CscPriceState.group == group)
            .order_by(CscPriceState.slot_index)
        )
    ).scalars().all()

    by_idx: dict[int, CscPriceState] = {r.slot_index: r for r in rows_db}
    products = _products_for(group)
    rows: list[CscRowDto] = []
    for i, name in enumerate(products):
        r = by_idx.get(i)
        prev = r.prev_price if r else 0
        change = r.change_amount if r else 0
        rows.append({
            "slot_index": i,
            "product_name": name,
            "prev_price": prev,
            "change_amount": change,
            "new_price": prev + change,
        })

    return {
        "group": group,
        "period_label": meta.period_label if meta else "",
        "announce_date": meta.announce_date if meta else "",
        "rows": rows,
    }


async def write_snapshot(
    db: AsyncSession,
    *,
    group: str,
    period_label: str,
    announce_date: str,
    rows: list[CscRowDto],
    updated_by: str | None,
) -> None:
    """Overwrite one group's rows + metadata in a single transaction.

    Raises ValueError if row count doesn't match the product list — better
    to fail loud than silently leave half a group written.
    """
    products = _products_for(group)
    if len(rows) != len(products):
        raise ValueError(
            f"group={group} expects {len(products)} rows, got {len(rows)}"
        )

    now = datetime.utcnow()

    meta = await db.get(CscAnnouncementMeta, group)
    if meta is None:
        meta = CscAnnouncementMeta(group=group)
    meta.period_label = period_label
    meta.announce_date = announce_date
    meta.updated_at = now
    meta.updated_by = updated_by
    db.add(meta)

    for r in rows:
        idx = r["slot_index"]
        existing = (
            await db.execute(
                select(CscPriceState).where(
                    CscPriceState.group == group,
                    CscPriceState.slot_index == idx,
                )
            )
        ).scalar_one_or_none()
        row = existing or CscPriceState(group=group, slot_index=idx)
        row.prev_price = int(r["prev_price"])
        row.change_amount = int(r["change_amount"])
        row.updated_at = now
        row.updated_by = updated_by
        db.add(row)

    await db.commit()

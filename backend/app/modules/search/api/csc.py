"""CSC (中鋼盤價) admin endpoints — read + overwrite the two snapshots.

Two groups, both admin-managed:
    GET /admin/search-csc/{group}  — anyone with search permission can read
    PUT /admin/search-csc/{group}  — admin only; overwrites all rows + meta

The frontend admin form posts back the entire group at once. We don't
expose partial updates — the row count must match the product list,
otherwise we fail with 400. Half-written groups would leave the table
inconsistent.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_admin, require_search_permission
from app.models.user import User
from app.search_database import get_search_db

from ..core.csc_products import MONTHLY_PRODUCTS, QUARTERLY_PRODUCTS
from ..storage import csc_repo
from .schemas import CscSnapshotOut, CscSnapshotWriteRequest

router = APIRouter(prefix="/admin/search-csc", tags=["search-admin-csc"])

GroupName = Literal["monthly", "quarterly"]


@router.get("/{group}", response_model=CscSnapshotOut)
async def get_csc_snapshot(
    group: GroupName,
    # search_enabled gates read access too — admin-only CSC reads would
    # block normal users from viewing the table even when they have
    # access to the rest of the SEARCH UI.
    _user: User = Depends(require_search_permission),
    db: AsyncSession = Depends(get_search_db),
) -> CscSnapshotOut:
    snap = await csc_repo.read_snapshot(db, group)
    return CscSnapshotOut(**snap)


@router.put("/{group}", response_model=CscSnapshotOut)
async def put_csc_snapshot(
    group: GroupName,
    body: CscSnapshotWriteRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_search_db),
) -> CscSnapshotOut:
    products = MONTHLY_PRODUCTS if group == "monthly" else QUARTERLY_PRODUCTS
    if len(body.rows) != len(products):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"group={group} expects {len(products)} rows, got {len(body.rows)}",
        )

    # Validate row order, then build the typed dict the repo expects.
    # product_name + new_price are derived here so the API contract
    # remains "send prev + change, server computes the rest".
    rows = []
    for i, r in enumerate(body.rows):
        if r.slot_index != i:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"row {i} has slot_index={r.slot_index}, expected {i}",
            )
        rows.append({
            "slot_index": i,
            "product_name": products[i],
            "prev_price": r.prev_price,
            "change_amount": r.change_amount,
            "new_price": r.prev_price + r.change_amount,
        })

    await csc_repo.write_snapshot(
        db,
        group=group,
        period_label=body.period_label,
        announce_date=body.announce_date,
        rows=rows,
        updated_by=str(admin.id),
    )
    snap = await csc_repo.read_snapshot(db, group)
    return CscSnapshotOut(**snap)

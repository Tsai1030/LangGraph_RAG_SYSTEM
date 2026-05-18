"""Pydantic DTOs for SEARCH HTTP endpoints.

Kept separate from app.modules.search.storage.models — DB schema and
HTTP schema evolve at different cadences (e.g. adding internal_data
fields shouldn't force a migration). Mirrors RAG's split of
app.schemas vs app.models.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


# ─── Generation ──────────────────────────────────────────────────────

class GenerationRunRequest(BaseModel):
    """POST /search/generation/run body."""
    meeting_date: date
    fengxing_open_date: date | None = None   # defaults to meeting_date if omitted


class CscRowIn(BaseModel):
    """One CSC row payload — prev + change; new_price is derived server-side."""
    slot_index: int
    prev_price: int
    change_amount: int


class CscOverrideGroup(BaseModel):
    """One group's worth of CSC values, sent from the wizard's CSC step.

    Shape matches the orchestrator's expected snapshot so a per-run
    override and the shared admin seed are read with the same code path.
    """
    period_label: str = ""
    announce_date: str = ""
    rows: list[CscRowIn] = []


class CscOverridePayload(BaseModel):
    """Optional per-run CSC override sent with internal-data."""
    monthly: CscOverrideGroup | None = None
    quarterly: CscOverrideGroup | None = None


class GenerationInternalDataRequest(BaseModel):
    """POST /search/generation/{id}/internal-data body.

    Free-form key/value map for slot data — keys are slot keys (validated
    by orchestrator against slot_schema, not here). Schema-level
    whitelisting would couple HTTP DTO to slot_schema and make adding new
    internal slots a two-place change.

    csc_override (optional, per-run): full snapshots the user edited in
    the wizard's CSC step. When present the orchestrator uses them
    verbatim and skips reading csc_price_state. Either group can be
    omitted to fall back to the shared admin seed.
    """
    internal_data: dict[str, str]
    csc_override: CscOverridePayload | None = None


class GenerationRunSummary(BaseModel):
    """Slim view used by /run, /internal-data, and the list endpoint."""
    id: int
    meeting_date: date
    started_by: str | None
    started_at: datetime
    finished_at: datetime | None
    status: str   # 'running' | 'success' | 'partial' | 'failed'
    notes: str

    model_config = {"from_attributes": True}


class SlotValueDto(BaseModel):
    """One slot's rendered + raw representation for the frontend.

    `value` is the formatted display string (already comma-grouped,
    delta-signed, etc.). `raw_value` is the numeric value from the
    source for charting / re-formatting; null for TEXT slots or
    missing data.
    """
    slot_key: str
    label: str
    value: str | None
    raw_value: float | None = None
    unit: str | None = None
    confidence: str = "high"
    source: str | None = None
    source_url: str | None = None


class GenerationStatusResponse(BaseModel):
    """Polling response from GET /search/generation/{run_id}."""
    run_id: int
    status: str   # 'running' | 'success' | 'partial' | 'failed'
    meeting_date: date
    slots: list[SlotValueDto] = []
    has_output: bool = False
    notes: str | None = None


# ─── CSC (中鋼月/季盤) ─ admin seed + per-run override share this row shape ─

class CscRowOut(BaseModel):
    slot_index: int
    product_name: str
    prev_price: int
    change_amount: int
    new_price: int


class CscSnapshotOut(BaseModel):
    group: str   # 'monthly' | 'quarterly'
    period_label: str
    announce_date: str
    rows: list[CscRowOut]


class CscSnapshotWriteRequest(BaseModel):
    period_label: str
    announce_date: str
    rows: list[CscRowIn]


# ─── Usage stats ─────────────────────────────────────────────────────

class UsageAggregateRow(BaseModel):
    """Per-user totals across all runs, shown in the admin usage table.

    user_id is the RAG users.id (UUID); email is joined from app.db at
    query time. Both nullable because legacy/unmapped runs have
    started_by=NULL after the migration.
    """
    user_id: str | None
    email: str | None
    display_name: str | None
    runs_total: int
    runs_success: int
    runs_failed: int
    runs_partial: int
    last_run_at: datetime | None


class UsageRunRow(BaseModel):
    """One row in the admin usage view (per generation run)."""
    id: int
    meeting_date: date
    started_by: str | None         # UUID
    started_by_email: str | None   # joined from app.db at query time
    started_at: datetime
    finished_at: datetime | None
    status: str
    duration_seconds: float | None

"""Generation endpoints — start run, poll status, push internal data, download.

Architecture mirror of SEARCH's original design, ported onto RAG's async
stack:

  - /run and /{id}/internal-data create / mutate a row in search.db,
    spawn a detached asyncio.Task that runs the LangGraph, and return
    immediately. The LangGraph takes 90-180s; blocking the HTTP request
    would risk Caddy/PM2 timeouts.
  - /{id} (polled by the frontend every ~2.5 s) reads the row and
    returns slot_values rebuilt from `result_json` on completion.
  - /{id}/docx streams the produced Word file.

Auth + permission:
    Every endpoint requires search_enabled via require_search_permission
    (admin role does NOT bypass — admin must enable themselves too).
    /{id}, /{id}/internal-data, /{id}/docx additionally check ownership:
    the run must belong to current_user, or current_user must be admin.
    Ownership failures return 404 (not 403) so we don't leak run IDs.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date as date_t
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_search_permission
from app.models.user import User
from app.search_database import SearchAsyncSessionLocal, get_search_db

from ..core.dates import opening_monday
from ..core.orchestrator import get_graph
from ..core.slot_schema import SLOTS
from ..sources.base import FetchResult
from ..storage import run_repo
from .schemas import (
    GenerationInternalDataRequest,
    GenerationRunRequest,
    GenerationStatusResponse,
    SlotValueDto,
)

router = APIRouter(prefix="/search/generation", tags=["search-generation"])
logger = logging.getLogger(__name__)


# asyncio.create_task holds only a weak ref to its task — if the parent
# function returns, the task can be GC'd before it finishes. We keep
# strong refs here and drop them in the done callback.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


# ─── helpers ─────────────────────────────────────────────────────────

def _is_admin(user: User) -> bool:
    return getattr(user, "role", "") == "admin"


def _serialise_state(final_state: dict[str, Any]) -> str:
    """Pack final graph state into a JSON blob for result_json column.

    Validated FetchResults need .model_dump() — they're pydantic. The
    blob is intentionally loose-typed so adding slot fields doesn't
    require a schema migration on the DB.
    """
    fetched_list: list[dict[str, Any]] = []
    for r in final_state.get("validated", []):
        if isinstance(r, FetchResult):
            fetched_list.append(r.model_dump())
        elif isinstance(r, dict):
            fetched_list.append(r)
    payload = {
        "slot_values": final_state.get("slot_values", {}),
        "confidence": final_state.get("confidence", {}),
        "fetched": fetched_list,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _deserialise_state(
    blob: str,
) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, Any]]]:
    if not blob:
        return {}, {}, {}
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        return {}, {}, {}
    slot_values = payload.get("slot_values") or {}
    confidence = payload.get("confidence") or {}
    fetched_index: dict[str, dict[str, Any]] = {}
    for item in payload.get("fetched") or []:
        key = item.get("slot_key")
        if key:
            fetched_index[key] = item
    return slot_values, confidence, fetched_index


def _format_response(
    *,
    run_id: int,
    status_str: str,
    meeting_date: date_t,
    slot_values: dict[str, str],
    confidence: dict[str, str],
    fetched_index: dict[str, Any] | None = None,
    output_path: str | None = None,
    notes: str | None = None,
) -> GenerationStatusResponse:
    fetched_index = fetched_index or {}
    slots: list[SlotValueDto] = []
    for s in SLOTS:
        rendered = slot_values.get(s.key)
        fetched = fetched_index.get(s.key)
        if fetched is None:
            raw_value, source_url = None, None
        elif isinstance(fetched, dict):
            raw_value = fetched.get("value")
            source_url = fetched.get("source_url")
        else:
            raw_value = getattr(fetched, "value", None)
            source_url = getattr(fetched, "source_url", None)
        slots.append(
            SlotValueDto(
                slot_key=s.key,
                label=s.label,
                value=rendered,
                raw_value=raw_value,
                unit=s.unit,
                confidence=confidence.get(s.key, "high"),
                source=s.source,
                source_url=source_url,
            )
        )
    return GenerationStatusResponse(
        run_id=run_id,
        status=status_str,
        meeting_date=meeting_date,
        slots=slots,
        has_output=bool(output_path) and Path(output_path).exists(),
        notes=notes,
    )


def _spawn(coro: Any) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


# ─── background worker ──────────────────────────────────────────────

async def _execute_graph_and_persist(
    *,
    run_id: int,
    meeting_date: date_t,
    fengxing_d: date_t,
    started_by: str,
    internal_data: dict[str, str],
) -> None:
    """Run the LangGraph, then persist result_json + final status.

    Runs detached from the HTTP request, so we cannot reuse the request's
    AsyncSession (FastAPI closes it when the request ends). Open a fresh
    session inside this task.

    Any exception is captured into the row's notes column — the polling
    endpoint surfaces it to the frontend.
    """
    try:
        graph = get_graph()
        initial_state: dict[str, Any] = {
            "run_id": run_id,
            "meeting_date": meeting_date,
            "fengxing_open_date": fengxing_d,
            "started_by": started_by,
            "internal_data": internal_data,
            "retry_count": 0,
            "max_retries": 3,
        }
        final_state = await graph.ainvoke(initial_state)
        output_path = final_state.get("output_path")
        issues = final_state.get("issues") or []
        new_status = "partial" if issues else "success"

        async with SearchAsyncSessionLocal() as db:
            await run_repo.update_status(
                db,
                run_id,
                status=new_status,
                output_path=output_path,
                result_json=_serialise_state(final_state),
                notes=("; ".join(str(i) for i in issues))[:500] if issues else "",
                finished_at=datetime.utcnow(),
            )
    except Exception as exc:   # noqa: BLE001 — want to capture *any* failure
        logger.exception("Generation run %s failed", run_id)
        async with SearchAsyncSessionLocal() as db:
            await run_repo.update_status(
                db,
                run_id,
                status="failed",
                notes=f"{type(exc).__name__}: {exc}"[:500],
                finished_at=datetime.utcnow(),
            )


# ─── endpoints ──────────────────────────────────────────────────────

@router.post("/run", response_model=GenerationStatusResponse)
async def start_run(
    body: GenerationRunRequest,
    user: User = Depends(require_search_permission),
    db: AsyncSession = Depends(get_search_db),
) -> GenerationStatusResponse:
    """Create a run row + spawn the LangGraph task. Returns within ~100ms.

    Client polls GET /{run_id} every ~2.5s until status != 'running'.
    """
    run = await run_repo.create(
        db,
        meeting_date=body.meeting_date,
        started_by=str(user.id),
    )
    fengxing_d = body.fengxing_open_date or opening_monday(body.meeting_date)
    _spawn(
        _execute_graph_and_persist(
            run_id=run.id,
            meeting_date=body.meeting_date,
            fengxing_d=fengxing_d,
            started_by=str(user.id),
            internal_data={},
        )
    )
    return GenerationStatusResponse(
        run_id=run.id,
        status="running",
        meeting_date=body.meeting_date,
        slots=[],
        has_output=False,
    )


@router.post("/{run_id}/internal-data", response_model=GenerationStatusResponse)
async def update_internal_data(
    run_id: int,
    body: GenerationInternalDataRequest,
    user: User = Depends(require_search_permission),
    db: AsyncSession = Depends(get_search_db),
) -> GenerationStatusResponse:
    """Re-render the Word doc after the user fills internal-data fields.

    Same async pattern as /run — flip status back to 'running', spawn the
    graph, return immediately. Polling /{run_id} resumes.
    """
    run = await run_repo.get(db, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    if run.started_by != str(user.id) and not _is_admin(user):
        # Ownership: 404 (not 403) so we don't leak run IDs.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    meeting_date = run.meeting_date
    await run_repo.update_status(db, run_id, status="running")

    fengxing_d = opening_monday(meeting_date)
    _spawn(
        _execute_graph_and_persist(
            run_id=run_id,
            meeting_date=meeting_date,
            fengxing_d=fengxing_d,
            started_by=str(user.id),
            internal_data=dict(body.internal_data),
        )
    )
    return GenerationStatusResponse(
        run_id=run_id,
        status="running",
        meeting_date=meeting_date,
        slots=[],
        has_output=False,
    )


@router.get("/{run_id}", response_model=GenerationStatusResponse)
async def get_run(
    run_id: int,
    user: User = Depends(require_search_permission),
    db: AsyncSession = Depends(get_search_db),
) -> GenerationStatusResponse:
    """Polling endpoint. Returns the run state; for completed runs the
    persisted result_json is rebuilt into the same shape the orchestrator
    produced in-memory."""
    run = await run_repo.get(db, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    if run.started_by != str(user.id) and not _is_admin(user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    if run.status == "running":
        return GenerationStatusResponse(
            run_id=run_id,
            status="running",
            meeting_date=run.meeting_date,
            slots=[],
            has_output=False,
        )

    if run.status == "failed":
        # Return 200 with status='failed' rather than HTTP error — the
        # frontend's polling loop expects to receive this terminal state
        # cleanly (not as a network error).
        return GenerationStatusResponse(
            run_id=run_id,
            status="failed",
            meeting_date=run.meeting_date,
            slots=[],
            has_output=False,
            notes=run.notes or "Unknown error — check backend logs",
        )

    slot_values, confidence, fetched_index = _deserialise_state(run.result_json)
    return _format_response(
        run_id=run_id,
        status_str=run.status,
        meeting_date=run.meeting_date,
        slot_values=slot_values,
        confidence=confidence,
        fetched_index=fetched_index,
        output_path=run.output_path,
        notes=run.notes or None,
    )


@router.get("/{run_id}/docx")
async def download_docx(
    run_id: int,
    user: User = Depends(require_search_permission),
    db: AsyncSession = Depends(get_search_db),
) -> FileResponse:
    run = await run_repo.get(db, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    if run.started_by != str(user.id) and not _is_admin(user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    if not run.output_path:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No Word output for this run — has it finished?",
        )
    path = Path(run.output_path)
    if not path.exists():
        # Real possibility after a worktree migration: output_path points
        # at a file in the old SEARCH/.../outputs/ tree. The plan says we
        # accept old docx as expired; surface 404 so frontend renders
        # "已過期，請重新產生".
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Output file no longer available — please regenerate.",
        )
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )


# Keep an explicit anchor for the `user` param in get_current_user-only
# routes (none currently — every search route needs require_search_permission,
# which already chains through get_current_user). Re-exporting here so a
# future read-only health/debug endpoint has it ready without re-import.
_ = get_current_user

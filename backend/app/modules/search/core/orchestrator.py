"""LangGraph orchestrator — fetch -> validate -> persist -> narrate -> render.

All nodes are async (LangGraph 1.x runs them concurrently when the topology
allows). Each node that needs DB access opens its own AsyncSession from
SearchAsyncSessionLocal — we never hand a session through state, because
state is JSON-serialisable in checkpointer scenarios.

Synchronous CPU work — the docx render — is wrapped in asyncio.to_thread
so it does not block the event loop while the rest of FastAPI serves
unrelated traffic.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.search_database import SearchAsyncSessionLocal

from ..output.docx_renderer import DocxRenderer
from ..sources.base import get_adapter
from ..storage import csc_repo, history_repo
from .dates import opening_monday
from .graph_state import GenerationState
from .slot_schema import HISTORY_TOPICS, SLOTS, SLOTS_BY_KEY, SlotType


def _format_roc_date(d: date) -> str:
    """ISO date -> 民國 format, e.g. 2026-05-04 -> '115/5/4'."""
    roc_year = d.year - 1911
    return f"{roc_year}/{d.month}/{d.day}"


def _format_roc_md(d: date) -> str:
    return f"{d.month}/{d.day}"


async def _node_fetch(state: GenerationState) -> dict:
    """Call every distinct source adapter referenced by an auto-fillable slot.

    Adapter.fetch is async (httpx.AsyncClient + AsyncOpenAI), so we gather
    them concurrently — different sources do not share rate limits.
    """
    fengxing_date = state.get("fengxing_open_date") or state["meeting_date"]
    source_names = {
        s.source for s in SLOTS_BY_KEY.values() if s.source and s.auto_fillable
    }

    async def _run(name: str):
        adapter_cls = get_adapter(name)
        adapter = adapter_cls()
        return await adapter.fetch(fengxing_date)

    chunks = await asyncio.gather(*(_run(n) for n in source_names))
    results = [r for chunk in chunks for r in chunk]
    return {"fetched": results}


async def _node_validate(state: GenerationState) -> dict:
    """Stage 1: flag any missing-but-expected value as a 'warn' issue."""
    issues = []
    validated = []
    for r in state.get("fetched", []):
        if r.value is None:
            issues.append({
                "slot_key": r.slot_key,
                "severity": "warn",
                "message": f"no value (confidence={r.confidence})",
            })
        validated.append(r)
    return {"validated": validated, "issues": issues}


async def _node_persist(state: GenerationState) -> dict:
    """Write numeric fetched results to price_history, keyed by opening Monday.

    Why a separate node? Idempotency: if narrate or render fails we still
    have the data; if validation flags problems we still record what we got
    (with low confidence) so future runs can backfill / detect drift.
    """
    user = state.get("started_by")
    raw_d = state.get("fengxing_open_date") or state["meeting_date"]
    monday = opening_monday(raw_d)
    async with SearchAsyncSessionLocal() as db:
        for r in state.get("validated", []):
            if r.value is None:
                continue   # don't pollute history with nulls
            await history_repo.upsert_price(db, r, monday, user)
    return {}


async def _node_narrate(state: GenerationState) -> dict:
    """Build {slot_key: rendered_string} from validated results + metadata."""
    slot_values: dict[str, str] = {}
    confidence: dict[str, str] = {}

    # ── 1. metadata slots ──
    meeting_d: date = state["meeting_date"]
    fengxing_d: date = state.get("fengxing_open_date") or meeting_d
    _WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]
    slot_values["meeting_date"] = meeting_d.isoformat()
    slot_values["meeting_date_roc"] = _format_roc_date(meeting_d)
    slot_values["meeting_weekday"] = _WEEKDAY_CN[meeting_d.weekday()]
    slot_values["meeting_time"] = ""   # supplied by internal_data merge step
    slot_values["fengxing_open_date_roc"] = _format_roc_md(fengxing_d)
    for k in ("meeting_date", "meeting_date_roc", "meeting_weekday",
              "meeting_time", "fengxing_open_date_roc"):
        confidence[k] = "high"

    # ── 2. fetched values ──
    for r in state.get("validated", []):
        slot_def = SLOTS_BY_KEY.get(r.slot_key)
        if slot_def and slot_def.type == SlotType.TEXT:
            text = (r.raw_text or "").strip()
            slot_values[r.slot_key] = text if text else "—"
        elif r.value is None:
            slot_values[r.slot_key] = "—"
        elif slot_def and slot_def.type == SlotType.PRICE:
            slot_values[r.slot_key] = f"{int(r.value):,}"
        else:
            slot_values[r.slot_key] = str(r.value)
        confidence[r.slot_key] = r.confidence

    # ── 3. internal slots default to '—' (overridden by internal-data POST) ──
    for s in SLOTS:
        if not s.auto_fillable and s.key not in slot_values:
            slot_values[s.key] = "—"
            confidence[s.key] = "low"

    # ── 4. apply any internal data supplied during this run ──
    for k, v in state.get("internal_data", {}).items():
        slot_values[k] = str(v)
        confidence[k] = "high"

    # ── 5 + 6. history + CSC slots (need their own session) ──
    async with SearchAsyncSessionLocal() as db:
        await _fill_history_slots(slot_values, confidence, db, opening_monday(meeting_d))
        await _fill_csc_slots(slot_values, confidence, db, state.get("csc_override"))

    return {"slot_values": slot_values, "confidence": confidence}


async def _fill_csc_slots(
    slot_values: dict[str, str],
    confidence: dict[str, str],
    db,
    override: dict[str, dict] | None,
) -> None:
    """Fill 中鋼 slot values, per-group.

    Source priority per group:
        1. `override[group]` if present (wizard's CSC step) — used verbatim,
           csc_repo not consulted. Shape must match read_snapshot output:
           {period_label, announce_date, rows: [{slot_index, prev_price,
           change_amount, ...}]}.
        2. csc_repo.read_snapshot(db, group) — the admin-seeded shared
           default. Same shape.

    The new_price column accepts a provided value but falls back to
    prev_price + change_amount when missing — frontends that only edit
    prev/change don't have to compute the sum.
    """
    override = override or {}
    for group, prefix in (("monthly", "m"), ("quarterly", "q")):
        snap = override.get(group) or await csc_repo.read_snapshot(db, group)
        period_key = f"csc_{group}_period"
        date_key = f"csc_{group}_announce_date"
        period_label = snap.get("period_label") or ""
        announce_date = snap.get("announce_date") or ""
        slot_values[period_key] = period_label or "—"
        slot_values[date_key] = announce_date or "—"
        confidence[period_key] = "high" if period_label else "low"
        confidence[date_key] = "high" if announce_date else "low"
        for row in snap.get("rows") or []:
            idx = row["slot_index"]
            prev = row.get("prev_price", 0)
            change = row.get("change_amount", 0)
            new = row.get("new_price")
            if new is None:
                new = prev + change
            empty = (prev == 0 and change == 0)
            for col_key, val in (
                (f"csc_{prefix}_{idx:02d}_prev",   prev),
                (f"csc_{prefix}_{idx:02d}_change", change),
                (f"csc_{prefix}_{idx:02d}_new",    new),
            ):
                if empty:
                    slot_values[col_key] = "—"
                    confidence[col_key] = "low"
                else:
                    if col_key.endswith("_change"):
                        slot_values[col_key] = f"+{val}" if val >= 0 else str(val)
                    else:
                        slot_values[col_key] = f"{val:,}"
                    confidence[col_key] = "high"


async def _fill_history_slots(
    slot_values: dict[str, str],
    confidence: dict[str, str],
    db,
    meeting_d: date,
) -> None:
    """Populate hist_d_h0..h6, hist_<topic>_h0..h6, hist_<topic>_v_h0..h6.

    h0 = current week (rightmost column); h6 = oldest displayed (leftmost).
    Empty cells render as '—' with low confidence.
    """
    DISPLAY = 7
    LOOKBACK = DISPLAY + 1   # one extra for the leftmost column's prior week

    # ── shared date headers from the densest topic ──
    raw_seed: list[tuple[date, float | None]] = []
    for _, src_key, _ in HISTORY_TOPICS:
        raw_seed = await history_repo.list_recent(db, src_key, meeting_d, count=LOOKBACK)
        if raw_seed:
            break
    while len(raw_seed) < LOOKBACK:
        raw_seed.insert(0, (None, None))   # type: ignore[arg-type]
    display_seed = raw_seed[-DISPLAY:]

    for i in range(DISPLAY):
        h_idx = (DISPLAY - 1) - i
        d, _ = display_seed[i]
        slot_key = f"hist_d_h{h_idx}"
        if d is None:
            slot_values[slot_key] = "—"
            confidence[slot_key] = "low"
        else:
            slot_values[slot_key] = f"{d.month}/{d.day}"
            confidence[slot_key] = "high"

    for topic_key, src_key, _ in HISTORY_TOPICS:
        pairs = await history_repo.list_recent(db, src_key, meeting_d, count=LOOKBACK)
        while len(pairs) < LOOKBACK:
            pairs.insert(0, (None, None))   # type: ignore[arg-type]
        display = pairs[-DISPLAY:]
        prior_for_first = pairs[-DISPLAY - 1]
        for i in range(DISPLAY):
            h_idx = (DISPLAY - 1) - i
            d_at_col, val = display[i]
            price_key = f"hist_{topic_key}_h{h_idx}"
            delta_key = f"hist_{topic_key}_v_h{h_idx}"
            if val is None:
                slot_values[price_key] = "未開盤" if d_at_col is not None else "—"
                slot_values[delta_key] = "—"
                confidence[price_key] = "high" if d_at_col is not None else "low"
                confidence[delta_key] = "low"
            else:
                slot_values[price_key] = f"{int(val):,}"
                confidence[price_key] = "high"
                prev_val = None
                for j in range(i - 1, -2, -1):
                    if j < 0:
                        prev_val = prior_for_first[1]
                        break
                    if display[j][1] is not None:
                        prev_val = display[j][1]
                        break
                if prev_val is None:
                    slot_values[delta_key] = "—"
                    confidence[delta_key] = "low"
                else:
                    diff = int(val - prev_val)
                    slot_values[delta_key] = f"+{diff}" if diff >= 0 else str(diff)
                    confidence[delta_key] = "high"


async def _node_render(state: GenerationState) -> dict:
    """Render the Word document using DocxRenderer.

    python-docx is synchronous + CPU-bound. asyncio.to_thread keeps the
    event loop responsive — without it the entire FastAPI process pauses
    for the seconds it takes to write the docx, blocking all unrelated
    /api/* traffic.

    Paths are resolved from settings (absolute via the backend root) so
    the run does not depend on the cwd of whatever invoked uvicorn.
    """
    meeting_d = state["meeting_date"]
    user = state.get("started_by") or "system"

    backend_root = Path(__file__).resolve().parents[4]   # backend/
    template_path = (backend_root / settings.search_template_path).resolve()
    output_dir = (backend_root / settings.search_output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    out_filename = (
        f"meeting_{meeting_d.isoformat()}_{user[:8]}_"
        f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.docx"
    )
    out_path = output_dir / out_filename

    renderer = DocxRenderer(template_path)
    await asyncio.to_thread(
        renderer.render,
        state.get("slot_values", {}),
        out_path,
        state.get("confidence", {}),
    )
    return {"output_path": str(out_path)}


def build_graph():
    """Compile the LangGraph workflow."""
    graph = StateGraph(GenerationState)
    graph.add_node("fetch", _node_fetch)
    graph.add_node("validate", _node_validate)
    graph.add_node("persist", _node_persist)
    graph.add_node("narrate", _node_narrate)
    graph.add_node("render", _node_render)

    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "validate")
    graph.add_edge("validate", "persist")
    graph.add_edge("persist", "narrate")
    graph.add_edge("narrate", "render")
    graph.add_edge("render", END)

    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph

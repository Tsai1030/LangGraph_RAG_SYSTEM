"""LangGraph state schema shared by all nodes.

Why a typed state? LangGraph passes a dict through every node; making it a
TypedDict gives type-checker support and prevents typos creating silent bugs.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from ..sources.base import FetchResult


class ValidationIssue(TypedDict):
    slot_key: str
    severity: str  # 'warn' | 'error'
    message: str


class GenerationState(TypedDict, total=False):
    """State carried through the LangGraph workflow.

    Nodes add to / overwrite fields. `messages` is the canonical
    LangGraph chat log for any LLM-using nodes.
    """

    # Inputs
    run_id: int
    meeting_date: date
    fengxing_open_date: date
    started_by: str
    internal_data: dict[str, str]  # supplied by Step 4 form
    # Per-run CSC override (option B): the wizard's CSC step ships the
    # full snapshots for both groups back through internal-data. When
    # present, narrate uses these values verbatim and skips reading
    # csc_repo. Shape:
    #   {"monthly":   {period_label, announce_date, rows: [...]},
    #    "quarterly": {period_label, announce_date, rows: [...]}}
    # Either group can be omitted to fall back to the shared seed in
    # csc_price_state. Set None / missing entirely to fall back for both.
    csc_override: dict[str, Any] | None

    # Outputs from each phase
    fetched: list[FetchResult]
    validated: list[FetchResult]
    issues: list[ValidationIssue]
    slot_values: dict[str, str]   # rendered strings ready for the docx template
    confidence: dict[str, str]    # slot_key -> 'high' | 'medium' | 'low'
    output_path: str | None

    # Retry control (used in Stage 2 self-correcting loop)
    retry_count: int
    max_retries: int

    # LLM messages
    messages: Annotated[list, add_messages]

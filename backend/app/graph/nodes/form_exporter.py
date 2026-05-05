"""
form_exporter.py — 把 prev_form_data 轉成 .xlsx / .csv 並設 state.exported_form_file

由 unified_intent 判定為 dynamic_form_export 後，builder 將控制權轉到此節點。
不會打 LLM，只做純檔案產出 + state 更新。
"""

from __future__ import annotations

import logging

from app.graph.state import GraphState
from app.services.dynamic_form_export import export_dynamic_form

logger = logging.getLogger(__name__)


async def form_exporter(state: GraphState) -> dict:
    prev = state.get("prev_form_data")
    if not prev:
        logger.warning("[form_exporter] 無 prev_form_data，跳過")
        return {}

    fmt = state.get("export_format") or "xlsx"
    conv_id = state.get("conversation_id", "anonymous")

    meta = export_dynamic_form(prev, conv_id, fmt=fmt)  # type: ignore[arg-type]
    if meta is None:
        return {}

    logger.info("[form_exporter] exported %s → %s", fmt, meta["display_name"])
    return {"exported_form_file": meta}

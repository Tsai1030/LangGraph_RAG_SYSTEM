"""Feng Hsin Steel (豐興鋼鐵) weekly-opening price extractor.

Powered by FengxingFinderAgent (LangGraph): given a target meeting date,
the agent searches steelnet.com.tw with year+month+keyword=豐興, picks the
correct weekly opening article (LLM tie-break for ambiguous candidates),
extracts SD280 from "本週牌價" line, derives other rebar grades.

User-supplied derivation rules:
    SD280W = SD280 + 200    (welded grade premium)
    SD420  = SD280 + 1000
    SD420W = SD420          (parity)

Each FetchResult.raw_text carries a one-line trace ("[search] ... [pick] ...
[validate] PASS — SD280=18900") so the user sees the agent's decision in
Step 3 of the UI without diving into backend logs.
"""
from __future__ import annotations

import logging
from datetime import date

from ..core.dates import opening_monday
from .base import FetchResult, SourceAdapter, register
from .fengxing_finder import find_article

logger = logging.getLogger(__name__)


def _slot_map() -> list[tuple[str, str]]:
    return [
        ("fx_sd280_price", "sd280"),
        ("fx_sd280w_price", "sd280w"),
        ("fx_sd420_price", "sd420"),
        ("fx_sd420w_price", "sd420w"),
        ("fx_scrap_base_price", "scrap"),
        ("fx_section_steel_price", "section"),
    ]


def _derive_grades(sd280: int) -> dict[str, int]:
    sd420 = sd280 + 1000
    return {
        "fx_sd280_price": sd280,
        "fx_sd280w_price": sd280 + 200,
        "fx_sd420_price": sd420,
        "fx_sd420w_price": sd420,
    }


@register
class FengxingAdapter(SourceAdapter):
    name = "fengxing"
    provides = [k for k, _ in _slot_map()]

    async def fetch(self, target_date: date) -> list[FetchResult]:
        opening_day = opening_monday(target_date)

        try:
            parsed, picked, trace = await find_article(target_date)
        except Exception as e:
            logger.exception("FengxingFinderAgent crashed")
            return self._fallback(
                target_date, reason=f"finder agent crashed: {type(e).__name__}: {e}"
            )

        # Always include the trace so the user can audit the agent's choice
        trace_summary = " | ".join(trace[-6:])  # last 6 log lines
        if parsed is None or parsed.sd280_price is None:
            logger.warning("FengxingAdapter: no usable article. trace: %s",
                           trace_summary)
            return self._fallback(
                target_date,
                reason=f"agent gave up. trace: {trace_summary[:200]}",
            )

        grades = _derive_grades(parsed.sd280_price)
        all_prices = {
            **grades,
            "fx_scrap_base_price": parsed.scrap_price or 0,
            "fx_section_steel_price": parsed.section_price or 0,
        }
        picked_url = picked["url"] if picked else ""
        picked_title = picked["title"] if picked else "(unknown)"
        # Build one-line note for the UI
        note = (
            f"agent picked: 「{picked_title}」 | "
            f"opening_date={parsed.opening_date or '未知'} | "
            f"trace: {trace_summary}"
        )

        return [
            FetchResult(
                slot_key=key,
                value=float(all_prices[key]),
                unit="元/噸",
                raw_text=note,
                source_url=f"https://www.steelnet.com.tw{picked_url}",
                confidence="high",
            )
            for key, _ in _slot_map()
        ]

    def _fallback(self, target_date: date, *, reason: str) -> list[FetchResult]:
        """Return placeholder rows so downstream nodes don't crash.

        All values None + confidence='low' → the renderer surfaces them
        as red "—" cells, making it obvious the agent didn't find data.
        We deliberately don't return any hardcoded numbers here; silent
        defaults would slip into a Word doc that looks complete.
        """
        _ = target_date
        return [
            FetchResult(
                slot_key=key,
                value=None,
                unit="元/噸",
                raw_text=f"[fallback: {reason}]",
                source_url="",
                confidence="low",
            )
            for key, _ in _slot_map()
        ]

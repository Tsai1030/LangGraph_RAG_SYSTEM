"""Feng Hsin Steel (豐興鋼鐵) weekly-opening price extractor.

Powered by fengxing_gemini.find_article (Gemini + Google Search): given a
target meeting date, it runs a grounded search for 豐興's opening prices that
week and extracts SD280 / 廢鋼 / 型鋼 absolute numbers via structured output,
then derives the other rebar grades. (Replaced the steelnet.com.tw scraping
agent after that site's subscription lapsed.)

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
from datetime import date, timedelta

from app.search_database import SearchAsyncSessionLocal

from ..core.dates import opening_monday
from ..storage import history_repo
from .base import FetchResult, SourceAdapter, register
from .fengxing_gemini import find_article

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


async def _recent_value(db, slot_key: str, cutoff: date) -> tuple[date, float] | None:
    """Most recent (value_date, value) for slot_key with a non-null value,
    on/before `cutoff`. price_history is returned ascending, so newest is last."""
    pairs = await history_repo.list_recent(db, slot_key, cutoff, count=4)
    for d, v in reversed(pairs):   # newest first
        if v is not None:
            return (d, float(v))
    return None


@register
class FengxingAdapter(SourceAdapter):
    name = "fengxing"
    provides = [k for k, _ in _slot_map()] + ["fx_adjustment_summary"]

    async def fetch(self, target_date: date) -> list[FetchResult]:
        opening_day = opening_monday(target_date)

        try:
            parsed, picked, trace = await find_article(target_date)
        except Exception as e:
            logger.exception("Fengxing Gemini fetch crashed")
            return await self._not_published_or_fallback(
                target_date, reason=f"fetch crashed: {type(e).__name__}: {e}"
            )

        # Always include the trace so the user can audit the agent's choice
        trace_summary = " | ".join(trace[-6:])  # last 6 log lines
        if parsed is None or parsed.sd280_price is None:
            logger.warning("FengxingAdapter: no usable price. trace: %s",
                           trace_summary)
            return await self._not_published_or_fallback(
                target_date,
                reason=f"未取得本週盤價. trace: {trace_summary[:200]}",
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

        results = [
            FetchResult(
                slot_key=key,
                value=float(all_prices[key]),
                unit="元/噸",
                raw_text=note,
                source_url=picked_url,
                confidence="high",
            )
            for key, _ in _slot_map()
        ]
        # §六.1 narrative summary sentence (dynamic — was static "皆維持平盤")
        results.append(FetchResult(
            slot_key="fx_adjustment_summary",
            value=None,
            unit="text",
            raw_text=(parsed.opening_paragraph or "本週開盤").strip(),
            source_url=picked_url,
            confidence="high",
        ))
        return results

    async def _not_published_or_fallback(
        self, target_date: date, *, reason: str
    ) -> list[FetchResult]:
        """本週查無 → 先嘗試沿用上週實際報價（標 is_stale）；
        連上週都沒有才退回紅「—」fallback。"""
        borrowed = await self._borrow_last_week(target_date)
        if borrowed is not None:
            return borrowed
        return self._fallback(target_date, reason=reason)

    async def _borrow_last_week(
        self, target_date: date
    ) -> list[FetchResult] | None:
        """豐興週一傍晚才公布；本週還沒出時，沿用上週實際報價並標註。

        Pull the most recent real prices strictly before this week's Monday,
        derive grades, mark is_stale=True (display-only). Returns None if there
        is no prior data to borrow (→ caller falls back to red '—').
        """
        monday = opening_monday(target_date)
        cutoff = monday - timedelta(days=1)
        async with SearchAsyncSessionLocal() as db:
            sd280 = await _recent_value(db, "fx_sd280_price", cutoff)
            scrap = await _recent_value(db, "fx_scrap_base_price", cutoff)
            section = await _recent_value(db, "fx_section_steel_price", cutoff)
        if sd280 is None:
            return None
        last_date, sd280_v = sd280
        grades = _derive_grades(int(sd280_v))
        all_prices = {
            **grades,
            "fx_scrap_base_price": int(scrap[1]) if scrap else 0,
            "fx_section_steel_price": int(section[1]) if section else 0,
        }
        note = (
            f"豐興本週尚未公布（通常傍晚公布），以下沿用上週 "
            f"{last_date.month}/{last_date.day} 報價，請稍後重新產生。"
        )
        logger.info("Fengxing not published; borrowing last week %s", last_date)
        results = [
            FetchResult(
                slot_key=key,
                value=float(all_prices[key]),
                unit="元/噸",
                raw_text=note,
                source_url="",
                confidence="low",
                is_stale=True,
            )
            for key, _ in _slot_map()
        ]
        results.append(FetchResult(
            slot_key="fx_adjustment_summary",
            value=None,
            unit="text",
            raw_text="本週尚未公布盤價，以下沿用上週報價",
            source_url="",
            confidence="low",
        ))
        return results

    def _fallback(self, target_date: date, *, reason: str) -> list[FetchResult]:
        """Return placeholder rows so downstream nodes don't crash.

        All values None + confidence='low' → the renderer surfaces them
        as red "—" cells, making it obvious the agent didn't find data.
        We deliberately don't return any hardcoded numbers here; silent
        defaults would slip into a Word doc that looks complete.
        """
        _ = target_date
        results = [
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
        results.append(FetchResult(
            slot_key="fx_adjustment_summary",
            value=None,
            unit="text",
            raw_text="",
            source_url="",
            confidence="low",
        ))
        return results

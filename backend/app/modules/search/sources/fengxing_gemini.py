"""Feng Hsin (豐興) weekly opening price fetcher — Gemini + Google Search.

Drop-in replacement for fengxing_finder.find_article after the
steelnet.com.tw subscription lapsed. Two steps:

  1. Gemini + GoogleSearch grounding → a live report of 豐興's opening
     prices for the target week (豐興 opens weekly on Monday).
  2. Gemini structured extraction (extract_json) → pull SD280 / 廢鋼 / 型鋼
     absolute numbers + the actual opening date out of that report.

Returns the SAME (FengxingArticleData, picked_meta, trace) tuple as the old
steelnet finder, so FengxingAdapter only swaps its import. SD280 is the only
rebar grade fetched; FengxingAdapter derives the rest (SD280W=+200,
SD420=+1000, SD420W=SD420) exactly as before.
"""
from __future__ import annotations

import logging
from datetime import date

from langsmith import traceable
from pydantic import BaseModel, Field

from ..core.dates import opening_monday
from ..llm import get_search_llm
from .steelnet_client import FengxingArticleData

logger = logging.getLogger(__name__)

# SD280 sanity bounds (元/噸) — same range the old steelnet validator used.
_SD280_MIN, _SD280_MAX = 15_000, 25_000


class FengxingExtract(BaseModel):
    """Structured pull from the grounded 豐興 report."""

    rebar_sd280_price: int | None = Field(
        default=None,
        description="豐興 鋼筋牌價 SD280 的絕對數值(元/噸)，查不到填 null",
    )
    scrap_base_price: int | None = Field(
        default=None,
        description="豐興 國內廢鋼【基價】的絕對數值(元/噸)，這是會議記錄採用的數字，查不到填 null",
    )
    scrap_purchase_price: int | None = Field(
        default=None,
        description="豐興 國內廢鋼【收購價/牌價】的絕對數值(元/噸)，查不到填 null",
    )
    section_steel_price: int | None = Field(
        default=None,
        description="豐興 型鋼牌價 的絕對數值(元/噸)，查不到填 null",
    )
    opening_date: str | None = Field(
        default=None,
        description="豐興本週實際開盤日期，格式 YYYY-MM-DD，查不到填 null",
    )
    adjustment_summary: str | None = Field(
        default=None,
        description="一句話總結本週相對上週調整，例如『廢鋼、鋼筋同步上調 200 元』或『鋼筋平盤』",
    )


def _search_prompt(monday: date) -> str:
    return (
        f"你是鋼鐵產業分析助手。請使用 Google 搜尋，查詢「豐興鋼鐵」在包含 "
        f"{monday.isoformat()}(週一)這一週公告的最新內銷盤價。\n"
        f"請找出並回報：\n"
        f"1. 鋼筋牌價(SD280)的絕對數值(例如 18,900 元/噸)\n"
        f"2. 國內廢鋼的「基價」與「收購價(牌價)」各自的絕對數值"
        f"(會議記錄採用的是基價)\n"
        f"3. 型鋼牌價的絕對數值\n"
        f"4. 豐興本週實際開盤日期\n"
        f"5. 本週相對上週的調整(上調/下調/平盤與金額)\n"
        f"規則：提供絕對數值(不要只給漲跌幅)；查不到的項目明確說「查無」；"
        f"絕對不要編造數字。"
    )


_EXTRACT_SYSTEM = (
    "你是鋼鐵盤價資料結構化助手。下面是剛從 Google 搜尋拿到的『豐興鋼鐵』本週開盤"
    "盤價報告，請把數字整理成 JSON。規則：只取豐興的盤價；數字一律整數(去掉逗號)；"
    "查不到的欄位填 null，絕對不要編造或推算。"
)


@traceable(run_type="chain", name="FengxingGemini.find_article")
async def find_article(
    target_date: date,
) -> tuple[FengxingArticleData | None, dict | None, list[str]]:
    """Public entry point. Returns (parsed, picked_article_meta, trace_log)."""
    monday = opening_monday(target_date)
    trace: list[str] = []
    client = get_search_llm()

    # 1) grounded search
    try:
        research = await client.web_search(_search_prompt(monday))
    except Exception as e:
        logger.warning("FengxingGemini web_search failed: %s", e)
        trace.append(f"[search] FAILED {type(e).__name__}: {e}")
        return None, None, trace
    report = research.get("text") or ""
    citations = research.get("citations") or []
    trace.append(
        f"[search] grounded report {len(report)} chars, {len(citations)} sources"
    )
    for c in citations[:3]:
        trace.append(f"[source] {(c.get('title') or '')[:40]} {c.get('url', '')[:70]}")

    # 2) structured extraction
    try:
        ext = await client.extract_json(
            system=_EXTRACT_SYSTEM,
            user=f"目標週(週一={monday.isoformat()})的豐興開盤報告：\n\n{report}",
            schema=FengxingExtract,
            max_tokens=800,
        )
    except Exception as e:
        logger.warning("FengxingGemini extract_json failed: %s", e)
        trace.append(f"[extract] FAILED {type(e).__name__}: {e}")
        return None, None, trace
    trace.append(
        f"[extract] SD280={ext.rebar_sd280_price} 廢鋼基價={ext.scrap_base_price} "
        f"廢鋼收購={ext.scrap_purchase_price} 型鋼={ext.section_steel_price} "
        f"開盤={ext.opening_date} 摘要={ext.adjustment_summary}"
    )

    # validate SD280 bounds (reject hallucinated / out-of-range numbers)
    sd280 = ext.rebar_sd280_price
    if sd280 is not None and not (_SD280_MIN <= sd280 <= _SD280_MAX):
        trace.append(
            f"[validate] SD280={sd280} 超出 [{_SD280_MIN},{_SD280_MAX}] → 視為查無"
        )
        sd280 = None

    parsed = FengxingArticleData()
    parsed.sd280_price = sd280
    # 會議記錄採用廢鋼「基價」；「收購價」只作後備
    parsed.scrap_price = (
        ext.scrap_base_price
        if ext.scrap_base_price is not None
        else ext.scrap_purchase_price
    )
    parsed.section_price = ext.section_steel_price
    parsed.opening_paragraph = ext.adjustment_summary or ""
    if ext.opening_date:
        try:
            y, m, d = ext.opening_date.split("-")
            parsed.opening_date = date(int(y), int(m), int(d))
        except (ValueError, AttributeError):
            parsed.opening_date = None

    picked = {
        "url": citations[0]["url"] if citations else "",
        "title": citations[0]["title"] if citations else "Gemini + Google 搜尋",
    }
    return parsed, picked, trace

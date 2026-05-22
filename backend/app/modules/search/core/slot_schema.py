"""Slot schema = single source of truth for every dynamic field in the template.

Adding a new field anywhere in the pipeline starts here:
1. Add a SlotDef entry
2. (If auto-fillable) add a SourceAdapter whose `provides` includes the key
3. The orchestrator, validator, renderer, and frontend all read from this schema.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel


class SlotType(str, Enum):
    PRICE = "price"        # numeric monetary / index value
    DELTA = "delta"        # week-over-week change (auto-computed)
    DATE = "date"          # ISO date
    TEXT = "text"          # short text (narrator-generated)
    INTERNAL = "internal"  # filled manually by staff (no auto-fetch)


class SlotDef(BaseModel):
    """Definition of one dynamic field in the meeting template."""

    key: str
    """Unique snake_case identifier used in template placeholders ({{key}})."""

    label: str
    """Human-readable Chinese name."""

    type: SlotType

    unit: str | None = None
    """e.g. "元/噸", "美元/噸", "點". None for TEXT/DATE/INTERNAL non-numeric."""

    source: str | None = None
    """Name of the SourceAdapter that produces this slot. None = INTERNAL."""

    confidence_required: Literal["high", "medium", "low"] = "high"
    """Minimum confidence to auto-fill without manual review."""

    auto_fillable: bool = True
    """If False, always shows a form field for staff to type."""

    section: str = ""
    """Which template section this belongs to (for grouping in UI)."""


# ──────────────────────────────────────────────────────────────
# Stage 1 slots — meeting metadata + Feng Hsin opening + a handful
# of internal placeholders.
#
# Other sections (中鋼盤價、國際廢鋼、近期盤價歷史表) remain as
# literal text in the template for now; they get slotified in later
# stages once their scrapers come online.
# ──────────────────────────────────────────────────────────────

SLOTS: list[SlotDef] = [
    # ─── Meeting metadata ────────────────────────────────
    SlotDef(
        key="meeting_date",
        label="會議日期 (ISO)",
        type=SlotType.DATE,
        section="meta",
        auto_fillable=False,
    ),
    SlotDef(
        key="meeting_date_roc",
        label="會議日期 (民國)",
        type=SlotType.TEXT,
        section="meta",
        auto_fillable=False,
    ),
    SlotDef(
        key="meeting_time",
        label="會議時間",
        type=SlotType.TEXT,
        section="meta",
        auto_fillable=False,
    ),
    SlotDef(
        key="meeting_weekday",
        label="星期幾 (一二三...)",
        type=SlotType.TEXT,
        section="meta",
        auto_fillable=True,  # auto-computed from meeting_date
    ),
    SlotDef(
        key="fengxing_open_date_roc",
        label="豐興開盤日 (民國 M/D)",
        type=SlotType.TEXT,
        section="meta",
        auto_fillable=False,
    ),

    # ─── Feng Hsin opening prices ───────────────────────
    SlotDef(
        key="fx_sd280_price",
        label="豐興 SD280 盤價",
        type=SlotType.PRICE,
        unit="元/噸",
        source="fengxing",
        section="fengxing",
    ),
    SlotDef(
        key="fx_sd280_delta",
        label="SD280 漲跌",
        type=SlotType.DELTA,
        unit="元",
        source=None,  # auto-computed from history
        section="fengxing",
    ),
    SlotDef(
        key="fx_sd280w_price",
        label="豐興 SD280W 盤價",
        type=SlotType.PRICE,
        unit="元/噸",
        source="fengxing",
        section="fengxing",
    ),
    SlotDef(
        key="fx_sd280w_delta",
        label="SD280W 漲跌",
        type=SlotType.DELTA,
        unit="元",
        source=None,  # mirrors fx_sd280_delta (SD280W = SD280 + 200 constant)
        section="fengxing",
    ),
    SlotDef(
        key="fx_sd420_price",
        label="豐興 SD420 盤價",
        type=SlotType.PRICE,
        unit="元/噸",
        source="fengxing",
        section="fengxing",
    ),
    SlotDef(
        key="fx_sd420_delta",
        label="SD420 漲跌",
        type=SlotType.DELTA,
        unit="元",
        source=None,  # mirrors fx_sd420w_delta (SD420 = SD420W parity)
        section="fengxing",
    ),
    SlotDef(
        key="fx_sd420w_price",
        label="豐興 SD420W 盤價",
        type=SlotType.PRICE,
        unit="元/噸",
        source="fengxing",
        section="fengxing",
    ),
    SlotDef(
        key="fx_sd420w_delta",
        label="SD420W 漲跌",
        type=SlotType.DELTA,
        unit="元",
        source=None,
        section="fengxing",
    ),
    SlotDef(
        key="fx_scrap_base_price",
        label="豐興廢鋼基價",
        type=SlotType.PRICE,
        unit="元/噸",
        source="fengxing",
        section="fengxing",
    ),
    SlotDef(
        key="fx_section_steel_price",
        label="豐興型鋼牌價",
        type=SlotType.PRICE,
        unit="元/噸",
        source="fengxing",
        section="fengxing",
    ),

    # ─── Internal (staff manually fills) ────────────────
    SlotDef(
        key="contract_remaining_tons",
        label="採購合約剩餘總量",
        type=SlotType.INTERNAL,
        unit="噸",
        section="internal",
        auto_fillable=False,
    ),
    SlotDef(
        key="contract_usable_until",
        label="可使用至",
        type=SlotType.INTERNAL,
        section="internal",
        auto_fillable=False,
    ),
    SlotDef(
        key="meeting_conclusion_last_week",
        label="上週會議結論",
        type=SlotType.INTERNAL,
        section="internal",
        auto_fillable=False,
    ),
    SlotDef(
        key="meeting_conclusion_this_week",
        label="本週會議結論",
        type=SlotType.INTERNAL,
        section="internal",
        auto_fillable=False,
    ),

    # ─── Section 六.2-4 — weekly external prices (LLM-narrated) ────
    SlotDef(
        key="intl_scrap_paragraph",
        label="六.2 國際廢鋼/鐵礦",
        type=SlotType.TEXT,
        source="weekly_market",
        section="market_open",
    ),
    # Numeric counterparts extracted from the same intl scrap paragraph,
    # used by Section 七 history tables.
    SlotDef(
        key="intl_jp2h_scrap_price",
        label="日本 2H 廢鋼 USD",
        type=SlotType.PRICE,
        unit="美元/噸",
        source="weekly_market",
        section="intl_numeric",
    ),
    SlotDef(
        key="intl_us_container_scrap_price",
        label="美國貨櫃廢鋼 USD",
        type=SlotType.PRICE,
        unit="美元/噸",
        source="weekly_market",
        section="intl_numeric",
    ),
    SlotDef(
        key="china_xiben_paragraph",
        label="六.3 大陸西本指數",
        type=SlotType.TEXT,
        source="xiben",
        section="market_open",
    ),
    SlotDef(
        key="lme_copper_paragraph",
        label="六.4 LME 銅價",
        type=SlotType.TEXT,
        source="weekly_market",
        section="market_open",
    ),

    # ─── Section 九 — LLM-narrated market commentary ────
    SlotDef(
        key="market_info_domestic",
        label="九.1 國內市場資訊",
        type=SlotType.TEXT,
        source="market_narrator",
        section="market_info",
    ),
    SlotDef(
        key="market_info_china",
        label="九.2 大陸市場資訊",
        type=SlotType.TEXT,
        source="market_narrator",
        section="market_info",
    ),
]


# ──────────────────────────────────────────────────────────────
# Section 七 — auto-computed history slots from price_history table.
# Convention: h0 = current week (rightmost column), h6 = 6 weeks ago.
# ──────────────────────────────────────────────────────────────

HISTORY_TOPICS = [
    # (topic_key, fetch_slot_key, label_zh)
    ("sd280",        "fx_sd280_price",                "鋼筋 SD280"),
    ("sd420w",       "fx_sd420w_price",               "鋼筋 SD420W"),
    ("scrap",        "fx_scrap_base_price",           "國內廢鋼"),
    ("jp2h",         "intl_jp2h_scrap_price",         "日本 2H 廢鋼"),
    ("us_container", "intl_us_container_scrap_price", "美國貨櫃廢鋼"),
]


def _gen_history_slots() -> list[SlotDef]:
    out: list[SlotDef] = []
    # 7 shared date headers
    for i in range(7):
        out.append(SlotDef(
            key=f"hist_d_h{i}",
            label=f"歷史日期 (-{i} 週)",
            type=SlotType.TEXT,
            section="history",
        ))
    # Each topic: 7 prices + 7 deltas
    for topic_key, _src_key, label_zh in HISTORY_TOPICS:
        for i in range(7):
            out.append(SlotDef(
                key=f"hist_{topic_key}_h{i}",
                label=f"{label_zh} (-{i} 週) 盤價",
                type=SlotType.PRICE,
                section="history",
            ))
            out.append(SlotDef(
                key=f"hist_{topic_key}_v_h{i}",
                label=f"{label_zh} (-{i} 週) 漲跌",
                type=SlotType.DELTA,
                section="history",
            ))
    return out


SLOTS.extend(_gen_history_slots())


# ──────────────────────────────────────────────────────────────
# Section 八 — 中鋼盤價 slots, sourced from CscPriceState admin form.
# ──────────────────────────────────────────────────────────────

from .csc_products import MONTHLY_PRODUCTS, QUARTERLY_PRODUCTS


def _gen_csc_slots() -> list[SlotDef]:
    out: list[SlotDef] = [
        SlotDef(key="csc_monthly_period",
                label="八.1 月盤期別 (e.g. 115 年 5 月份)",
                type=SlotType.TEXT, section="csc", auto_fillable=False),
        SlotDef(key="csc_monthly_announce_date",
                label="八.1 月盤公告日 (e.g. 2026/4/15)",
                type=SlotType.TEXT, section="csc", auto_fillable=False),
        SlotDef(key="csc_quarterly_period",
                label="八.2 季盤期別 (e.g. 115 年第二季)",
                type=SlotType.TEXT, section="csc", auto_fillable=False),
        SlotDef(key="csc_quarterly_announce_date",
                label="八.2 季盤公告日 (e.g. 2026/3/19)",
                type=SlotType.TEXT, section="csc", auto_fillable=False),
    ]
    for i, name in enumerate(MONTHLY_PRODUCTS):
        out.append(SlotDef(key=f"csc_m_{i:02d}_prev",
                           label=f"月盤 {name} 上月基價",
                           type=SlotType.PRICE, unit="元/未稅",
                           section="csc", auto_fillable=False))
        out.append(SlotDef(key=f"csc_m_{i:02d}_change",
                           label=f"月盤 {name} 調整金額",
                           type=SlotType.DELTA, unit="元",
                           section="csc", auto_fillable=False))
        out.append(SlotDef(key=f"csc_m_{i:02d}_new",
                           label=f"月盤 {name} 調整後基價",
                           type=SlotType.PRICE, unit="元/未稅",
                           section="csc", auto_fillable=False))
    for i, name in enumerate(QUARTERLY_PRODUCTS):
        out.append(SlotDef(key=f"csc_q_{i:02d}_prev",
                           label=f"季盤 {name} 上季基價",
                           type=SlotType.PRICE, unit="元/未稅",
                           section="csc", auto_fillable=False))
        out.append(SlotDef(key=f"csc_q_{i:02d}_change",
                           label=f"季盤 {name} 調整金額",
                           type=SlotType.DELTA, unit="元",
                           section="csc", auto_fillable=False))
        out.append(SlotDef(key=f"csc_q_{i:02d}_new",
                           label=f"季盤 {name} 調整後基價",
                           type=SlotType.PRICE, unit="元/未稅",
                           section="csc", auto_fillable=False))
    return out


SLOTS.extend(_gen_csc_slots())

SLOTS_BY_KEY: dict[str, SlotDef] = {s.key: s for s in SLOTS}


def get_slots_by_source(source_name: str) -> list[SlotDef]:
    """All slots produced by a given source adapter."""
    return [s for s in SLOTS if s.source == source_name]


def get_internal_slots() -> list[SlotDef]:
    """All slots requiring manual staff input."""
    return [s for s in SLOTS if not s.auto_fillable]

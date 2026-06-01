"""Weekly external market data — Section 六.2 (international scrap / iron ore)
and 六.4 (LME copper).

六.2 國際廢鋼/鐵礦 — structured pipeline (same spirit as xiben, replaced the
old steelnet-article + free-form-LLM path after the subscription lapsed):
  1. web_search the four topics (US ocean / container scrap, JP 2H, AU iron ore)
  2. extract_json → per-item 本週 value + week-over-week delta + no_quote flag
  3. Python composes the paragraph deterministically (no LLM wording drift),
     and emits the JP 2H + US container numerics for §七.4 / §七.5.

六.4 LME 銅 — still LLM-narrated from web_search (unchanged; whitelist prompt
+ 3-tier fallback).
  Tier 1: target-week data → write paragraph.
  Tier 2: ≤14-day-old data → write paragraph, label the date.
  Tier 3: nothing usable → the single fixed "本週尚未有公開報價資料" sentence.
  Hard rule: never substitute 0, X, — for missing numbers.
"""
from __future__ import annotations

import logging
from datetime import date

from pydantic import BaseModel, Field

from ..llm import LLMClient, get_search_llm
from .base import FetchResult, SourceAdapter, register

logger = logging.getLogger(__name__)

# Target format for §六.2 (deterministically reproduced by _compose_intl_paragraph):
#   "本週美國大船廢鋼無報價，美國貨櫃廢鋼上漲 1 元至 363 美元/噸，
#    日本 2H 廢鋼本週持平為 385 美元/噸，澳洲鐵礦上漲 0.70 元至 109.75 美元/噸。"
_LME_COPPER_EXAMPLE = (
    "上週 115/4/24 收盤價 13,246.81 美元/噸，"
    "115/5/1 收盤價 12,916.40 美元/噸(當週下跌 330.41 美元/噸)。"
)


# ── 六.2 結構化國際廢鋼/鐵礦 ──────────────────────────────────

class IntlScrapItem(BaseModel):
    value: float | None = Field(
        default=None, description="本週絕對數值(美元/噸)，查不到或無報價填 null"
    )
    delta: float | None = Field(
        default=None, description="相對上週的變動(美元)，持平填 0，查不到填 null"
    )
    no_quote: bool = Field(
        default=False, description="該項本週確實『無報價』時為 true"
    )


class IntlScrapSnapshot(BaseModel):
    us_ocean_scrap: IntlScrapItem = Field(
        default_factory=IntlScrapItem, description="美國大船廢鋼(HMS)"
    )
    us_container_scrap: IntlScrapItem = Field(
        default_factory=IntlScrapItem, description="美國貨櫃廢鋼"
    )
    jp2h_scrap: IntlScrapItem = Field(
        default_factory=IntlScrapItem, description="日本 2H 廢鋼"
    )
    au_iron_ore: IntlScrapItem = Field(
        default_factory=IntlScrapItem, description="澳洲鐵礦砂"
    )


def _fmt_usd(v: float) -> str:
    """363.0 -> '363'; 109.75 -> '109.75'; 0.7 -> '0.7'."""
    return f"{int(v):,}" if float(v).is_integer() else f"{v:g}"


def _intl_clause(name: str, item: IntlScrapItem) -> str:
    if item.no_quote or item.value is None:
        return f"{name}無報價"
    if item.delta is None or item.delta == 0:
        return f"{name}本週持平為 {_fmt_usd(item.value)} 美元/噸"
    verb = "上漲" if item.delta > 0 else "下跌"
    return f"{name}{verb} {_fmt_usd(abs(item.delta))} 元至 {_fmt_usd(item.value)} 美元/噸"


def _compose_intl_paragraph(snap: IntlScrapSnapshot) -> str:
    clauses = [
        _intl_clause("美國大船廢鋼", snap.us_ocean_scrap),
        _intl_clause("美國貨櫃廢鋼", snap.us_container_scrap),
        _intl_clause("日本 2H 廢鋼", snap.jp2h_scrap),
        _intl_clause("澳洲鐵礦", snap.au_iron_ore),
    ]
    return "本週" + "，".join(clauses) + "。"


# ── 六.4 LME 銅 — LLM narrate (unchanged) ────────────────────

def _build_prompt(
    *,
    target_date: date,
    topic_zh: str,
    style_example: str,
    research_text: str,
    extra_rules: str = "",
) -> tuple[str, str]:
    system = (
        "你是台灣鋼鐵採購會議的市場數據分析員。你的任務是把網路上找到的"
        "本週鋼鐵相關行情，整理成一段「會議記錄」格式的純敘述段落。"
        "用語：繁體中文（台灣用語），半正式書面，含資訊量。"
    )
    user = f"""請依下方參考資料，撰寫一段 {topic_zh}（目標週包含 {target_date.isoformat()} 那一週）的本週行情敘述。

【寫作風格範例（必須完全比照句型、單位、漲跌字眼）】
{style_example}

【本週參考資料（你剛剛上網查到的）】
{research_text}

【輸出規則 — 3 階段 fallback，必須嚴格遵守】

優先順序 1：若參考資料有目標週（{target_date.isoformat()} 那週）的真實數字，
            直接撰寫段落。

優先順序 2：若沒有目標週數字，但有過去 14 天內的最近一週資料，
            **使用該資料**並在段落首句標明日期。
            範例寫法：「截至 5/9 公佈之資料，<topic>...」
            日期用阿拉伯數字 + 斜線（5/9，不要寫民國年）。

優先順序 3：若連近 14 天資料都沒有，輸出**這一句**就好（不要加其他內容）：
            「{topic_zh}本週尚未有公開報價資料。」

【絕對禁止的寫法（負面範例）】
- ❌ 0、X、—、null、N/A 當數字
- ❌ markdown、項目符號、超連結、引文標記

{extra_rules}
"""
    return system, user


def _looks_garbage(text: str) -> bool:
    """Reject obvious failure modes that slipped past the prompt.

    Be CONSERVATIVE — better to keep an awkwardly-worded paragraph that
    contains real numbers than to discard everything and hand the user the
    bare fallback sentence. We only reject patterns that are clearly wrong.
    """
    if not text or len(text.strip()) < 10:
        return True
    if "0 美元/噸" in text or "0元/噸" in text or "—/噸" in text or "null" in text:
        return True
    import re
    for m in re.finditer(r"[上下][漲跌]\s*([\d,.]+)\s*[^/]{0,4}至\s*([\d,.]+)", text):
        if m.group(1) == m.group(2):
            return True
    return False


@register
class WeeklyMarketAdapter(SourceAdapter):
    name = "weekly_market"
    provides = [
        "intl_scrap_paragraph",
        "lme_copper_paragraph",
        "intl_jp2h_scrap_price",
        "intl_us_container_scrap_price",
    ]

    # ── 六.2 國際廢鋼/鐵礦 — structured Gemini pipeline ──────────

    async def _fetch_intl_scrap(
        self, client: LLMClient, target_date: date
    ) -> list[FetchResult]:
        query = (
            f"請查詢包含 {target_date.isoformat()} 那一週的國際廢鋼與鐵礦行情，"
            f"並提供本週的絕對數值(美元/噸)與相對上週的漲跌(美元)：\n"
            f"1. 美國大船廢鋼(HMS)，若本週無報價請明確說明無報價\n"
            f"2. 美國貨櫃廢鋼\n"
            f"3. 日本 2H 廢鋼\n"
            f"4. 澳洲鐵礦砂\n"
            f"請提供絕對數值(不要只給漲跌幅)；查不到的項目明確說查無。"
        )
        try:
            research = await client.web_search(query)
        except Exception as e:
            logger.warning("intl scrap web_search failed: %s", e)
            return self._intl_fallback()
        report = research.get("text") or ""
        citations = research.get("citations") or []

        try:
            snap = await client.extract_json(
                system=(
                    "你是國際鋼鐵原物料行情結構化助手。把下方搜尋結果整理成 JSON："
                    "每項給本週絕對數值 value(美元/噸)與相對上週變動 delta(美元；持平填 0)；"
                    "該項本週確實無報價時 no_quote=true 且 value=null；"
                    "查不到 value=null、delta=null。不要編造數字。"
                ),
                user=f"目標週(含 {target_date.isoformat()})的國際廢鋼/鐵礦搜尋結果：\n\n{report}",
                schema=IntlScrapSnapshot,
                max_tokens=900,
            )
        except Exception as e:
            logger.warning("intl scrap extract_json failed: %s", e)
            return self._intl_fallback()

        paragraph = _compose_intl_paragraph(snap)
        source_url = citations[0]["url"] if citations else ""

        results = [FetchResult(
            slot_key="intl_scrap_paragraph",
            value=None,
            unit="text",
            raw_text=paragraph,
            source_url=source_url,
            confidence="medium",
        )]
        # Numerics for §七.4 / §七.5 history tables
        for slot_key, item in (
            ("intl_jp2h_scrap_price", snap.jp2h_scrap),
            ("intl_us_container_scrap_price", snap.us_container_scrap),
        ):
            v = None if (item.no_quote or item.value is None) else float(item.value)
            results.append(FetchResult(
                slot_key=slot_key,
                value=v,
                unit="美元/噸",
                raw_text="Gemini 國際廢鋼結構化抽取",
                source_url=source_url,
                confidence="high" if v is not None else "low",
            ))
        return results

    def _intl_fallback(self) -> list[FetchResult]:
        return [
            FetchResult(slot_key="intl_scrap_paragraph", value=None, unit="text",
                        raw_text="國際廢鋼/鐵礦行情本週尚未有公開報價資料。",
                        source_url="", confidence="low"),
            FetchResult(slot_key="intl_jp2h_scrap_price", value=None, unit="美元/噸",
                        raw_text="[intl fallback]", source_url="", confidence="low"),
            FetchResult(slot_key="intl_us_container_scrap_price", value=None,
                        unit="美元/噸", raw_text="[intl fallback]",
                        source_url="", confidence="low"),
        ]

    # ── orchestration ───────────────────────────────────────────

    async def fetch(self, target_date: date) -> list[FetchResult]:
        client = get_search_llm()
        results: list[FetchResult] = []

        # 六.2 國際廢鋼/鐵礦 — structured pipeline
        results.extend(await self._fetch_intl_scrap(client, target_date))

        # 六.4 LME 倫敦銅 — LLM narrate from web_search
        plan = [
            {
                "slot": "lme_copper_paragraph",
                "topic": "LME 倫敦銅現貨收盤價",
                "queries": [
                    f"LME copper cash settlement {target_date.year} May USD per ton "
                    f"weekly close",
                ],
                "example": _LME_COPPER_EXAMPLE,
                "extra": (
                    f"日期格式：民國年(如 {target_date.year - 1911})/月/日，"
                    f"例如 {target_date.year - 1911}/5/8。"
                    "段落必須包含上週、本週兩個收盤日的價格與週變動方向(上漲/下跌/持平)。"
                    "若搜尋結果只有單一日期，使用該日期+前一週同日；"
                    "若資料中只有月度均價沒有週收盤價，仍可使用，但要明標日期。"
                ),
            },
        ]

        for entry in plan:
            try:
                research_chunks: list[str] = []
                citations: list[dict[str, str]] = []
                for q in entry["queries"]:
                    r = await client.web_search(q)
                    if r["text"]:
                        research_chunks.append(f"[query: {q}]\n{r['text']}")
                    citations.extend(r["citations"])

                combined_research = "\n\n".join(research_chunks) or "(無搜尋結果)"

                system, user = _build_prompt(
                    target_date=target_date,
                    topic_zh=entry["topic"],
                    style_example=entry["example"],
                    research_text=combined_research,
                    extra_rules=entry["extra"],
                )
                paragraph = (await client.chat(system, user, max_tokens=900)).strip()

                if _looks_garbage(paragraph):
                    paragraph = f"{entry['topic']}本週尚未有公開報價資料。"
                    confidence = "low"
                else:
                    confidence = "medium"

                seen = set()
                deduped = []
                for c in citations:
                    u = c.get("url", "")
                    if u and u not in seen:
                        seen.add(u)
                        deduped.append(c)

                results.append(FetchResult(
                    slot_key=entry["slot"],
                    value=None,
                    unit="text",
                    raw_text=paragraph,
                    source_url=deduped[0]["url"] if deduped else "",
                    confidence=confidence,
                ))
            except Exception as e:
                results.append(FetchResult(
                    slot_key=entry["slot"],
                    value=None,
                    unit="text",
                    raw_text=(
                        f"{entry['topic']}本週尚未有公開報價資料。"
                        f"  [error: {type(e).__name__}]"
                    ),
                    source_url="",
                    confidence="low",
                ))

        return results

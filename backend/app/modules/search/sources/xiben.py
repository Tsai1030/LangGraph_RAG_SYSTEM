"""西本新幹線（steelx2.com）週對比指數 — Section 六.3「大陸方面」。

Single output slot: china_xiben_paragraph.

Pipeline (same hybrid spirit as fengxing adapter):
  Phase 1 — web_search + extract_json over 5 designated steelx2.com URLs,
            pull `this_monday` and `last_monday` values for each of the 5
            indices (鋼材／鐵礦砂／焦炭／廢鋼／鋼胚).
  Phase 2 — Python computes delta and NT$ conversion (deterministic),
            LLM only assembles the final paragraph in the prescribed style.

Why this split?
  - LLM is excellent at navigating tables on real web pages and matching
    a date to a row (Phase 1).
  - LLM is *unreliable* at arithmetic and at choosing the right verb when
    delta sign flips. Doing the math in Python and feeding LLM a pre-built
    fact table makes the output deterministic up to formatting.

Date convention (與豐興一致):
  - 本週 = opening_monday(target_date)
  - 上週 = 本週 - 7 天
  - 若該週一是假日/無資料：取該日期之前最近一個有資料的交易日
    （LLM 自行從表格找；回報實際取到的日期供 trace）
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from pydantic import BaseModel

from app.config import settings

from ..core.dates import opening_monday
from ..llm.openai_client import OpenAIClient
from .base import FetchResult, SourceAdapter, register

logger = logging.getLogger(__name__)


# Style anchor — final paragraph must mirror this exactly in tone, punctuation,
# unit notation, and verb whitelist.
_STYLE_EXAMPLE = (
    "西本新幹線本週鋼材指數下跌 10 元至 3,500 元人民幣/噸(約 NT$15,894 元)，"
    "鐵礦砂本週持平指數為 980 元人民幣/噸(約 NT$4,450 元)，"
    "焦炭本週持平指數為 1,330 元人民幣/噸(約 NT$6,040 元)，"
    "廢鋼下跌 10 元至 2,040 元人民幣/噸(約 NT$9,264 元)，"
    "鋼胚上漲 20 元至 3,040 元人民幣/噸(約 NT$13,805 元)。"
)

# Designated source URLs. Order in this dict drives the output sentence order
# (鋼材 → 鐵礦砂 → 焦炭 → 廢鋼 → 鋼胚), matching the PDF template.
_SOURCES: list[tuple[str, str, str]] = [
    # (snapshot_field, 中文名稱, URL)
    ("steel",    "鋼材指數", "https://www.steelx2.com/indices/65/index.html"),
    ("iron_ore", "鐵礦砂",   "https://www.steelx2.com/indices/61/index.html"),
    ("coke",     "焦炭",     "https://www.steelx2.com/indices/64/index.html"),
    ("scrap",    "廢鋼",     "https://www.steelx2.com/indices/78/index.html"),
    ("billet",   "鋼胚",     "https://www.steelx2.com/indices/79/index.html"),
]


class XibenItem(BaseModel):
    this_week_value: float | None = None
    this_week_date: str | None = None   # YYYY-MM-DD actually used (may differ from monday)
    last_week_value: float | None = None
    last_week_date: str | None = None


class XibenSnapshot(BaseModel):
    steel:    XibenItem
    iron_ore: XibenItem
    coke:     XibenItem
    scrap:    XibenItem
    billet:   XibenItem


_FALLBACK_SENTENCE = "西本新幹線本週尚未有公開報價資料。"


def _fmt_roc(d: date) -> str:
    return f"{d.year - 1911}/{d.month}/{d.day}"


def _verb_phrase(delta: int) -> str:
    """Map signed delta to the whitelisted Chinese verb fragment."""
    if delta == 0:
        return "本週持平指數為"
    if delta > 0:
        return f"上漲 {delta} 元至"
    return f"下跌 {abs(delta)} 元至"


@register
class XibenAdapter(SourceAdapter):
    name = "xiben"
    provides = ["china_xiben_paragraph"]

    async def fetch(self, target_date: date) -> list[FetchResult]:
        this_monday = opening_monday(target_date)
        last_monday = this_monday - timedelta(days=7)

        client = OpenAIClient()
        try:
            snapshot = await self._extract_snapshot(client, this_monday, last_monday)
        except Exception as e:
            return [self._fallback(reason=f"extract failed: {type(e).__name__}: {e}")]

        # Build the deterministic fact table.
        rows = self._build_rows(snapshot)
        if rows is None:
            return [self._fallback(reason="snapshot missing values for one or more indices")]

        try:
            paragraph = await self._compose_paragraph(client, rows)
        except Exception as e:
            return [self._fallback(reason=f"compose failed: {type(e).__name__}: {e}")]

        # Trace goes to log (NOT raw_text — that gets dumped into the docx as-is
        # for TEXT slots, see orchestrator._node_narrate).
        trace = "; ".join(
            f"{r['name']} 本週={r['this_date']} 上週={r['last_date']}" for r in rows
        )
        logger.info("XibenAdapter dates used: %s", trace)
        return [FetchResult(
            slot_key="china_xiben_paragraph",
            value=None,
            unit="text",
            raw_text=paragraph,
            source_url=_SOURCES[0][2],
            confidence="high",
        )]

    # ── Phase 1: structured extraction ────────────────────────

    async def _extract_snapshot(
        self,
        client: OpenAIClient,
        this_monday: date,
        last_monday: date,
    ) -> XibenSnapshot:
        url_lines = "\n".join(
            f"- {label}：{url}" for _, label, url in _SOURCES
        )
        query = (
            f"我要查西本新幹線（西本指數）5 個指數在以下兩個日期的歷史數值：\n"
            f"- 本週基準日：{this_monday.isoformat()}（民國 {_fmt_roc(this_monday)}，週一）\n"
            f"- 上週基準日：{last_monday.isoformat()}（民國 {_fmt_roc(last_monday)}，週一）\n\n"
            f"請從這 5 個指定網址的歷史資料表抓對應日期那一列：\n{url_lines}\n\n"
            "【日期取值規則】\n"
            "1. 優先：取表格中該日期那一列的「值」欄位（不是漲跌額）。\n"
            "2. 若該日期是國定假日／週末／無交易（表格沒有該列），"
            "取該日期之前最近一個有資料的交易日的值。\n"
            "3. 不要外推、不要插值、不要用相鄰日期平均。\n"
            "4. 回報你實際取到的日期（YYYY-MM-DD）。"
        )
        research = await client.web_search(query)
        research_text = research["text"] or "(無搜尋結果)"

        extract_system = (
            "你是鋼鐵指數資料結構化助手。下面的文字是剛剛從 web_search 拿到的"
            "西本新幹線 5 個指數的當週/上週數值與日期，請把它整理成 JSON。"
            "規則：本週基準日為週一，若該日無資料則取該日之前最近的交易日；"
            "每個指數都要回報實際取到的日期（YYYY-MM-DD）。"
            "若某個指數的某個日期完全找不到，該欄位填 null（不要編造）。"
        )
        extract_user = (
            f"目標本週日期：{this_monday.isoformat()}\n"
            f"目標上週日期：{last_monday.isoformat()}\n\n"
            f"【web_search 取得的內容】\n{research_text}"
        )
        return await client.extract_json(
            system=extract_system,
            user=extract_user,
            schema=XibenSnapshot,
            max_tokens=1500,
        )

    # ── Phase 1.5: deterministic fact table ───────────────────

    def _build_rows(self, snapshot: XibenSnapshot) -> list[dict] | None:
        """Convert XibenSnapshot → list of fact rows for Phase 2.

        Returns None if ANY of the 5 indices is missing either value
        (triggers fallback paragraph per D7).
        """
        fx = settings.cny_to_twd_rate
        rows: list[dict] = []
        for field, label, _url in _SOURCES:
            item: XibenItem = getattr(snapshot, field)
            if item.this_week_value is None or item.last_week_value is None:
                return None
            this_v = int(round(item.this_week_value))
            last_v = int(round(item.last_week_value))
            delta = this_v - last_v
            ntd = int(round(this_v * fx))
            rows.append({
                "name": label,
                "this_value_fmt": f"{this_v:,}",
                "last_value_fmt": f"{last_v:,}",
                "delta": delta,
                "verb": _verb_phrase(delta),
                "ntd_fmt": f"{ntd:,}",
                "this_date": item.this_week_date or "?",
                "last_date": item.last_week_date or "?",
            })
        return rows

    # ── Phase 2: compose paragraph ────────────────────────────

    async def _compose_paragraph(
        self,
        client: OpenAIClient,
        rows: list[dict],
    ) -> str:
        # Pre-built fact table — LLM only assembles the sentence.
        fact_lines = []
        for r in rows:
            fact_lines.append(
                f"- {r['name']}：本週值={r['this_value_fmt']}、上週值={r['last_value_fmt']}、"
                f"漲跌={r['delta']:+d}、句型片段=「{r['verb']} {r['this_value_fmt']} 元人民幣/噸」、"
                f"NT$ 換算=「約 NT${r['ntd_fmt']} 元」"
            )
        facts_block = "\n".join(fact_lines)

        system = (
            "你是台灣鋼鐵採購會議的市場數據編輯。任務：把已備妥的 5 個指數事實表"
            "組裝成一段「### 3. 大陸方面」段落。**禁止**自己重算數字、改動句型、"
            "添加任何來源以外的資訊。用語：繁體中文（台灣用語），半正式書面。"
        )
        user = f"""請依下方事實表組裝成單一段落：

【事實表（依此順序、所有數字一字不漏照抄）】
{facts_block}

【寫作風格範例（必須完全比照）】
{_STYLE_EXAMPLE}

【嚴格輸出規則】
1. 段落開頭固定為「西本新幹線」。
2. 5 個指數依事實表順序串成單一段落，項目之間用「，」分隔，段末用「。」。
3. 每個項目必須包含：項目名、句型片段（含數字與單位）、括號內 NT$ 換算。
4. 句型只能用：「下跌 D 元至 N 元人民幣/噸」「上漲 D 元至 N 元人民幣/噸」「本週持平指數為 N 元人民幣/噸」。
5. 嚴禁：markdown、項目符號、超連結、引文、表格、換行、英數字 0 當數字、—、null、N/A。
6. 不可加任何前言、結語、註解、來源說明。
7. 完整輸出單一段落即可，不要包在引號或程式碼框內。

格式自我檢查：你輸出的句子裡，每個「上漲 D 元至 N」「下跌 D 元至 N」的 D 必須來自事實表的「漲跌」欄位（取絕對值）、N 必須來自「本週值」欄位。
"""
        text = (await client.chat(system, user, max_tokens=1200)).strip()
        # Defensive: strip any stray markdown fences the model might add
        if text.startswith("```"):
            text = text.strip("`").lstrip("markdown").strip()
        return text

    # ── fallback ──────────────────────────────────────────────

    def _fallback(self, *, reason: str) -> FetchResult:
        logger.warning("XibenAdapter fallback: %s", reason)
        return FetchResult(
            slot_key="china_xiben_paragraph",
            value=None,
            unit="text",
            raw_text=_FALLBACK_SENTENCE,
            source_url="",
            confidence="low",
        )

"""LLM-driven narrator for Section 九 — 其他市場資訊.

Generates two short paragraphs:
  1. 國內資訊 — Taiwan rebar/steel market commentary for the target week
  2. 大陸資訊 — China steel-export / CBAM commentary

Method (per slot):
  1. web_search a curated set of queries to find recent (≤ 7 days) news.
  2. Synthesize into a single paragraph in the same tone/style as the
     existing 5/4 PDF examples (few-shot prompt).
  3. Return as FetchResult with value=None, raw_text=<paragraph>.

We deliberately separate the two queries so the renderer slot map stays clean:
each paragraph maps 1:1 to a SlotDef.
"""
from __future__ import annotations

from datetime import date

from ..llm import get_search_llm
from .base import FetchResult, SourceAdapter, register

# Anchor texts from the 5/4 PDF — used as style examples in the prompt
# so the LLM matches register, length, vocabulary.
_DOMESTIC_STYLE_EXAMPLE = (
    "當前國內鋼筋市場正處於成本支撐與剛性需求並存的格局，目前鋼筋盤價"
    "連 3 週開出平盤（4/20、4/27、5/4），主要是「高檔觀望」與「供需拉鋸」"
    "的典型盤整現象，並非市況轉弱。國際廢鋼與海運費用的雙重墊高，"
    "使鋼廠生產成本居高不下，價格易漲難跌；加上國內高科技建廠與公共工程"
    "需求穩健，預期短期內鋼價將在高檔震盪，並密切關注國際廢鋼報價波動與"
    "地緣政治對物流的影響，以防範價格再度向上調整的採購風險。"
)
_CHINA_STYLE_EXAMPLE = (
    "大陸今年正式實施鋼鐵出口許可證制度，嚴格控管低價鋼材外銷，"
    "改變了過去「低價傾銷」的模式。面對各國反傾銷制裁與歐盟 CBAM 碳關稅壓力，"
    "大陸官方主動削減高能耗的鋼品出口，預期 2026 全年出口量將減少約 "
    "1,000 萬公噸（年減逾 8%）。大陸減少外銷後，國際買家轉向台灣下單，"
    "使中鋼、中鴻、燁輝等台廠迎來顯著的轉機，大陸預計 5 月行情維持"
    "「前穩後緩、價格續升」的態勢。"
)


def _build_narrative_prompt(
    *,
    target_date: date,
    topic_zh: str,
    style_example: str,
    research_text: str,
    research_citations: list[dict[str, str]],
) -> tuple[str, str]:
    """Return (system, user) for the narrative-writing LLM call."""
    citations_lines = "\n".join(
        f"- {c.get('title') or '(no title)'}: {c.get('url')}"
        for c in research_citations[:10]
    ) or "（無引文）"

    system = (
        "你是台灣鋼鐵採購會議的市場分析專員，專責撰寫週報內的「其他市場資訊」"
        "段落。寫作風格須完全比照公司既有版型：書面、簡潔、半正式、含資訊量但不情緒化。"
        "請使用繁體中文（台灣用語）。"
    )

    user = f"""請依下方參考資料，撰寫一段 {topic_zh}（目標日期：{target_date.isoformat()}）的市場敘述。

【寫作風格範例（必須比照）】
{style_example}

【本次參考資料（你剛剛上網查到的）】
{research_text}

【引用來源】
{citations_lines}

【嚴格要求】
1. 只輸出一段純文字段落（150~300 字之間），不要加標題、項目符號、引號或 markdown。
2. 內容必須基於參考資料，不可捏造數字或政策。
3. 若參考資料不足以支撐某個論點，省略該論點而不是虛構。
4. 文末不需要附引文，引文已由系統另行記錄。
"""
    return system, user


@register
class MarketNarratorAdapter(SourceAdapter):
    name = "market_narrator"
    provides = ["market_info_domestic", "market_info_china"]

    async def fetch(self, target_date: date) -> list[FetchResult]:
        client = get_search_llm()
        results: list[FetchResult] = []

        # Each entry: (slot_key, search_query, topic_label, style_example)
        plan = [
            (
                "market_info_domestic",
                f"台灣鋼筋 鋼鐵 市場 平盤 漲跌 {target_date.year}年{target_date.month}月 本週",
                "台灣國內鋼筋／鋼鐵市場概況",
                _DOMESTIC_STYLE_EXAMPLE,
            ),
            (
                "market_info_china",
                f"中國 鋼鐵 出口 CBAM 限產 {target_date.year}年{target_date.month}月 本週 行情",
                "中國大陸鋼鐵市場與政策動態",
                _CHINA_STYLE_EXAMPLE,
            ),
        ]

        for slot_key, query, topic, example in plan:
            try:
                # 1. live web research
                research = await client.web_search(query)
                # 2. write the paragraph in the prescribed style
                system, user = _build_narrative_prompt(
                    target_date=target_date,
                    topic_zh=topic,
                    style_example=example,
                    research_text=research["text"],
                    research_citations=research["citations"],
                )
                paragraph = (await client.chat(system, user, max_tokens=1200)).strip()

                citations = research["citations"]
                source_url = citations[0]["url"] if citations else ""

                results.append(FetchResult(
                    slot_key=slot_key,
                    value=None,             # TEXT slot — value lives in raw_text
                    unit="text",
                    raw_text=paragraph,
                    source_url=source_url,
                    confidence="medium",     # LLM-generated → require human review
                ))
            except Exception as e:
                results.append(FetchResult(
                    slot_key=slot_key,
                    value=None,
                    unit="text",
                    raw_text=f"[generation failed: {type(e).__name__}: {e}]",
                    source_url="",
                    confidence="low",
                ))

        return results

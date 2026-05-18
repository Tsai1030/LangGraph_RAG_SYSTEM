"""LangGraph agent that finds the right 豐興 weekly opening article for a
given target Monday.

Why an agent (and not just procedural code)?
  - The right article changes every week and titles vary
    ("豐興本週開盤", "豐興今(11)日上午開出週盤", "豐興今日開出 5 月第一盤", ...).
  - Some weeks have 2-3 豐興 news articles, only one is the price one.
  - LLM is good at saying "of these 5 titles + dates, which is the weekly
    opening for week containing 2026-03-16?".

Graph topology:

      ┌────────────────┐
      │ search_listing │  POST /news6.htm s_year/s_month/strKey1=豐興
      └────────┬───────┘
               ▼
      ┌────────────────┐    ──no candidates── expand → search_listing
      │  rank_pick     │  ←──────────────────────────────────┐
      │  LLM picks     │                                      │
      │  best title    │                                      │
      └────────┬───────┘                                      │
               ▼                                              │
      ┌────────────────┐                                      │
      │ fetch_extract  │  GET picked URL, parse              │
      └────────┬───────┘                                      │
               ▼                                              │
      ┌────────────────┐  invalid (no SD280) ───────retry────┘
      │   validate     │
      └────────┬───────┘
               ▼ valid
              END

Logging: every node appends a one-line trace into state['log']. The trace is
also surfaced through FengxingAdapter.fetch() into FetchResult.raw_text so
the user can see the agent's decisions in Step 3 of the UI.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import traceable

from ..core.dates import opening_monday
from ..llm.openai_client import OpenAIClient
from .steelnet_client import (
    FengxingArticleData,
    invalidate_session,
    parse_fengxing_opening_article,
    shared_session,
)

logger = logging.getLogger(__name__)


def _add_log(existing: list[str], new: list[str]) -> list[str]:
    """LangGraph reducer for the log field."""
    return existing + new


class FengxingFinderState(TypedDict, total=False):
    target_monday: date
    search_year: int
    search_month: int
    search_attempts: int          # how many month windows we've tried
    candidates: list[dict]        # [{url, title, date_str}, ...]
    tried_urls: list[str]
    picked_url: str
    picked_title: str
    body: str
    extracted: FengxingArticleData
    final: FengxingArticleData | None
    final_article: dict | None
    log: Annotated[list[str], _add_log]


# ───────────────────────────── nodes ─────────────────────────────

async def _node_search_listing(state: FengxingFinderState) -> dict:
    year = state.get("search_year") or state["target_monday"].year
    month = state.get("search_month") or state["target_monday"].month
    msg = f"[search] year={year} month={month} keyword=豐興 (max 3 pages)"
    logger.info(msg)
    async with shared_session() as sn:
        candidates = await sn.search_news(
            year=year, month=month, keyword="豐興", max_pages=3,
        )
    summary = (
        f"[search] ← {len(candidates)} candidates: "
        + ", ".join(f"{c['date_str']} {c['title'][:30]}" for c in candidates[:8])
    )
    logger.info(summary)
    return {
        "candidates": candidates,
        "log": [msg, summary],
    }


async def _node_rank_pick(state: FengxingFinderState) -> dict:
    """Pick the best candidate by date proximity to target Monday.

    LLM is invoked only when multiple candidates are roughly equally close —
    this keeps API cost down while preserving the "agent" choice for hard cases.
    """
    candidates = state.get("candidates", [])
    tried = set(state.get("tried_urls", []))
    untried = [c for c in candidates if c["url"] not in tried]
    if not untried:
        return {"log": ["[rank] no untried candidates left"]}

    target = state["target_monday"]

    def _parse(d: str) -> date | None:
        try:
            y, m, d_ = d.split("/")
            return date(int(y), int(m), int(d_))
        except Exception:
            return None

    # Compute |date_diff| from target Monday
    scored: list[tuple[int, dict, date | None]] = []
    for c in untried:
        d = _parse(c["date_str"])
        diff = abs((d - target).days) if d else 9999
        scored.append((diff, c, d))
    scored.sort(key=lambda x: x[0])

    # If best is within 3 days, deterministic pick
    best_diff, best, best_date = scored[0]
    if best_diff <= 3:
        msg = (
            f"[rank] pick {best['url']} (date={best['date_str']}, "
            f"diff={best_diff}d, title='{best['title'][:60]}')"
        )
        logger.info(msg)
        return {
            "picked_url": best["url"],
            "picked_title": best["title"],
            "log": [msg],
        }

    # Otherwise let the LLM decide among top-N (N ≤ 3)
    top = scored[:3]
    n = len(top)
    options = [
        f"{i+1}. date={c['date_str']} title=「{c['title']}」 url={c['url']}"
        for i, (_, c, _) in enumerate(top)
    ]
    valid_choices = "、".join(str(i + 1) for i in range(n))
    prompt = (
        f"目標日期是 {target.isoformat()}（豐興每週一開盤）。下列是候選文章：\n"
        + "\n".join(options)
        + "\n\n哪一篇是該週（包含 "
        + target.isoformat()
        + f" 那週週一）的「豐興本週開盤」價格新聞？"
        + f"回覆只用一個阿拉伯數字（{valid_choices}），不要任何其他文字。"
    )
    try:
        client = OpenAIClient()
        reply = (await client.chat(
            system=f"你是台灣鋼鐵新聞分類助手，只能回覆 {valid_choices} 其中之一。",
            user=prompt,
            max_tokens=10,
        )).strip()
        # Extract first digit anywhere in reply (handles "選 2" / "2." / "答案：1" etc.)
        import re as _re
        m = _re.search(r"[1-9]", reply)
        if not m:
            raise ValueError(f"no digit in reply: {reply!r}")
        idx = int(m.group(0)) - 1
        if not 0 <= idx < n:
            raise ValueError(f"out of range: {idx} (n={n}, reply={reply!r})")
    except Exception as e:
        msg = f"[rank] LLM failed ({e}), falling back to closest-date={best['url']}"
        logger.warning(msg)
        return {
            "picked_url": best["url"],
            "picked_title": best["title"],
            "log": [msg],
        }
    chosen = top[idx][1]
    msg = (
        f"[rank-LLM] LLM picked option {idx+1}: {chosen['date_str']} "
        f"「{chosen['title'][:60]}」"
    )
    logger.info(msg)
    return {
        "picked_url": chosen["url"],
        "picked_title": chosen["title"],
        "log": [msg],
    }


async def _node_fetch_extract(state: FengxingFinderState) -> dict:
    url = state.get("picked_url")
    if not url:
        return {"log": ["[fetch] nothing to fetch"]}
    msg = f"[fetch] GET {url}"
    logger.info(msg)
    async with shared_session() as sn:
        body = await sn.fetch_article_body(url)
    # If we get a member-only stub, the cached session was kicked off →
    # invalidate and retry once.
    if body is not None and len(body) < 300 and "非會員" in body:
        logger.warning("[fetch] member-only stub detected, invalidating session")
        invalidate_session()
        async with shared_session() as sn:
            body = await sn.fetch_article_body(url)
    if body is None:
        return {
            "body": "",
            "log": [msg + " → empty body"],
            "tried_urls": list(set(state.get("tried_urls", []) + [url])),
        }
    target = state["target_monday"]
    parsed = parse_fengxing_opening_article(
        body, fallback_year=target.year, fallback_month=target.month
    )
    snippet = body[:200].replace("\n", " ")
    log = [
        msg + f" → body={len(body)} bytes",
        f"[body-snippet] {snippet}",
        f"[parse] SD280={parsed.sd280_price} 廢鋼={parsed.scrap_price} "
        f"型鋼={parsed.section_price} opening={parsed.opening_date}",
    ]
    return {
        "body": body,
        "extracted": parsed,
        "log": log,
        "tried_urls": list(set(state.get("tried_urls", []) + [url])),
    }


def _node_validate(state: FengxingFinderState) -> dict:
    parsed = state.get("extracted")
    if parsed is None or parsed.sd280_price is None:
        return {"log": ["[validate] FAIL — no SD280, will retry next candidate"]}
    # Sanity bounds: SD280 typical range 15,000-25,000 元/噸
    if not (15_000 <= parsed.sd280_price <= 25_000):
        return {
            "log": [
                f"[validate] FAIL — SD280={parsed.sd280_price} out of [15000,25000]"
            ]
        }
    msg = f"[validate] PASS — SD280={parsed.sd280_price}"
    logger.info(msg)
    return {
        "final": parsed,
        "final_article": {
            "url": state.get("picked_url", ""),
            "title": state.get("picked_title", ""),
        },
        "log": [msg],
    }


def _node_expand_window(state: FengxingFinderState) -> dict:
    """Move search window one month earlier (covers "first week of month" case
    where the relevant article was published in prior month).

    Always increments `search_attempts` so the route function below can detect
    "we've given up" by the counter alone — keeping route logic simple and
    avoiding the off-by-one infinite loop we had before.
    """
    attempts = state.get("search_attempts", 0)
    if attempts >= 2:
        # Sentinel: bumping past 2 lets _route_after_expand return END.
        return {
            "search_attempts": attempts + 1,
            "log": [f"[expand] giving up after {attempts} window expansions"],
        }
    cur_y = state.get("search_year") or state["target_monday"].year
    cur_m = state.get("search_month") or state["target_monday"].month
    new_m = cur_m - 1 if cur_m > 1 else 12
    new_y = cur_y if cur_m > 1 else cur_y - 1
    msg = f"[expand] retry with prior month {new_y}/{new_m}"
    logger.info(msg)
    return {
        "search_year": new_y,
        "search_month": new_m,
        "search_attempts": attempts + 1,
        "candidates": [],
        "log": [msg],
    }


# ───────────────────── routing edges ─────────────────────

def _route_after_rank(state: FengxingFinderState) -> str:
    return "fetch_extract" if state.get("picked_url") else "expand_window"


# If a month yields more than this many failed attempts, we assume we're
# in the wrong month (e.g. the right article got pushed to prior month).
# Avoids burning 20 fetches on a wrong-month listing.
_MAX_TRIES_PER_MONTH = 8


def _route_after_validate(state: FengxingFinderState) -> str:
    if state.get("final") is not None:
        return END
    candidates = state.get("candidates", [])
    tried = set(state.get("tried_urls", []))
    untried = [c for c in candidates if c["url"] not in tried]
    # Cap: stop trying this month after _MAX_TRIES_PER_MONTH failed candidates
    tried_in_this_month = sum(1 for c in candidates if c["url"] in tried)
    if untried and tried_in_this_month < _MAX_TRIES_PER_MONTH:
        return "rank_pick"
    return "expand_window"


def _route_after_expand(state: FengxingFinderState) -> str:
    if state.get("search_attempts", 0) > 2:
        return END
    return "search_listing"


# ───────────────────────────── build & cache ─────────────────────────────

_compiled = None


def get_finder_graph():
    global _compiled
    if _compiled is None:
        g = StateGraph(FengxingFinderState)
        g.add_node("search_listing", _node_search_listing)
        g.add_node("rank_pick", _node_rank_pick)
        g.add_node("fetch_extract", _node_fetch_extract)
        g.add_node("validate", _node_validate)
        g.add_node("expand_window", _node_expand_window)

        g.add_edge(START, "search_listing")
        g.add_edge("search_listing", "rank_pick")
        g.add_conditional_edges(
            "rank_pick", _route_after_rank,
            {"fetch_extract": "fetch_extract", "expand_window": "expand_window"},
        )
        g.add_edge("fetch_extract", "validate")
        g.add_conditional_edges(
            "validate", _route_after_validate,
            {"rank_pick": "rank_pick", "expand_window": "expand_window", END: END},
        )
        g.add_conditional_edges(
            "expand_window", _route_after_expand,
            {"search_listing": "search_listing", END: END},
        )
        _compiled = g.compile()
    return _compiled


@traceable(run_type="chain", name="FengxingFinderAgent.find_article")
async def find_article(target_date: date) -> tuple[FengxingArticleData | None,
                                                   dict | None,
                                                   list[str]]:
    """Public entry point. Returns (parsed, picked_article_meta, trace_log)."""
    monday = opening_monday(target_date)
    graph = get_finder_graph()
    final_state = await graph.ainvoke({
        "target_monday": monday,
        "tried_urls": [],
        "candidates": [],
        "log": [],
    })
    return (
        final_state.get("final"),
        final_state.get("final_article"),
        final_state.get("log", []),
    )

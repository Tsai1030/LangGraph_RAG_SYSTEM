"""steelnet.com.tw (華文專業鋼鐵網) session client.

Why a dedicated client?
  - The site is behind member login. We must POST EMail + password + csrf
    + action=ok to /login.htm before anything member-only is accessible.
  - 豐興 weekly opening data lives inside a free-text news article whose
    URL is NOT fixed (newsid increments daily; multiple articles per day;
    only one per week is the "週盤 opening" article). We therefore search
    the news listing, narrow to weekly-opening candidates, and pick the
    first one whose body actually contains the price line.

Login flow (reverse-engineered from /login.htm JS):
  1. GET /login.htm  → get PHPSESSID cookie + csrf hidden input.
  2. POST /login.htm with {EMail, password, action=ok, csrf}.
  3. Subsequent fetches send the PHPSESSID cookie automatically.
"""
from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import httpx
from bs4 import BeautifulSoup
from langsmith import traceable

from app.config import settings

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class SteelnetAuthError(RuntimeError):
    """Login failed — credentials missing / bad / account expired."""


class SteelnetClient:
    """One logged-in HTTP session against steelnet.com.tw.

    Pass `cached_cookies` to skip the expensive login round-trip and re-use
    a previously valid PHPSESSID. The session pool below uses this so a
    multi-step agent doesn't kick its own previous session off the server.
    """

    def __init__(self, *, cached_cookies: dict[str, str] | None = None) -> None:
        if not settings.steelnet_user or not settings.steelnet_password:
            raise SteelnetAuthError(
                "STEELNET_USER / STEELNET_PASSWORD must be set in .env"
            )
        self._user = settings.steelnet_user
        self._password = settings.steelnet_password
        self._base = settings.steelnet_base
        self._cached_cookies = cached_cookies
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "SteelnetClient":
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        )
        if self._cached_cookies:
            for k, v in self._cached_cookies.items():
                self._client.cookies.set(k, v, domain="www.steelnet.com.tw")
        else:
            await self._login()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def get_cookies(self) -> dict[str, str]:
        """Snapshot current cookies for caching."""
        return dict(self._client.cookies) if self._client else {}

    # ── login ─────────────────────────────────────────────
    async def _login(self) -> None:
        assert self._client is not None
        r = await self._client.get("/login.htm")
        if r.status_code != 200:
            raise SteelnetAuthError(f"GET /login.htm returned {r.status_code}")
        soup = BeautifulSoup(r.text, "lxml")
        forms = soup.find_all("form")
        login_form = None
        for f in forms:
            if f.find("input", {"name": "EMail"}):
                login_form = f
                break
        if login_form is None:
            raise SteelnetAuthError("login form not found on /login.htm")
        csrf_input = login_form.find("input", {"name": "csrf"})
        csrf = csrf_input.get("value", "") if csrf_input else ""

        await self._client.post(
            "/login.htm",
            data={
                "EMail": self._user,
                "password": self._password,
                "action": "ok",
                "csrf": csrf,
            },
            headers={
                "Referer": f"{self._base}/login.htm",
                "Origin": self._base,
            },
        )
        # verify
        check = await self._client.get("/news-detail10033.htm")
        if len(check.text) < 1000 or "非會員只能看標題" in check.text:
            raise SteelnetAuthError(
                "Login appeared to succeed but member content not accessible — "
                "check credentials or account subscription state."
            )

    # ── public methods ────────────────────────────────────

    async def fetch_fengxing_market_price(self) -> dict[str, tuple[int, int]]:
        """Last-resort fallback: parse /market_price2.htm structured table.

        Returns dict like {"鋼筋": (18900, 0), ...}. Raises on failure.
        """
        assert self._client is not None
        r = await self._client.get("/market_price2.htm")
        soup = BeautifulSoup(r.text, "lxml")
        table = soup.find("table")
        result: dict[str, tuple[int, int]] = {}
        if table is None:
            return result
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
            if len(cells) < 3:
                continue
            item = cells[0].split("｜")[0].strip()
            if item not in ("廢鋼", "鋼筋", "型鋼"):
                continue
            try:
                delta = int(cells[1].replace(",", "").replace("+", ""))
                price = int(cells[2].replace(",", ""))
            except ValueError:
                continue
            result[item] = (price, delta)
        return result

    @traceable(run_type="tool", name="steelnet.search_news")
    async def search_news(
        self,
        *,
        year: int,
        month: int,
        keyword: str,
        category_class: str = "6",  # 6 = 台灣鋼鐵
        max_pages: int = 3,
    ) -> list[dict[str, str]]:
        """Filter /news6.htm by year+month+keyword. Walks up to `max_pages`
        pages (10 results each).

        Returns deduped list of {url, title, date_str}, newest first.
        """
        assert self._client is not None
        # Need a fresh CSRF token rendered on /news6.htm
        r = await self._client.get("/news6.htm")
        soup = BeautifulSoup(r.text, "lxml")
        csrf_input = soup.find("input", {"name": "csrf"})
        csrf = csrf_input.get("value", "") if csrf_input else ""

        date_re = re.compile(r"(\d{4}/\d{1,2}/\d{1,2})")
        seen_urls: set[str] = set()
        results: list[dict[str, str]] = []

        for page in range(1, max_pages + 1):
            r = await self._client.post(
                "/news6.htm",
                data={
                    "s_year": str(year),
                    "s_month": str(month),
                    "strKey1": keyword,
                    "Class1": category_class,
                    "Class2": category_class,
                    "this_lang": "1",
                    "csrf": csrf,
                    "Page": str(page),
                    "Page2": str(page),
                },
                headers={"Referer": f"{self._base}/news6.htm"},
            )
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, "lxml")
            page_added = 0
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "news-detail" not in href:
                    continue
                text = a.get_text(" ", strip=True)
                if keyword not in text:
                    continue
                full = href if href.startswith("http") else f"/{href.lstrip('/')}"
                if full in seen_urls:
                    continue
                seen_urls.add(full)
                m = date_re.search(text)
                date_str = m.group(1) if m else ""
                title = text
                if date_str:
                    title = text.split(date_str, 1)[1].strip()
                    if "｜" in title:
                        parts = title.split("|", 1)
                        if len(parts) == 2 and "News" in parts[0]:
                            title = parts[1].strip()
                results.append({"url": full, "title": title, "date_str": date_str})
                page_added += 1
            if page_added == 0:
                break  # empty page → no more results
        return results

    @traceable(run_type="tool", name="steelnet.fetch_article")
    async def fetch_article_body(self, url: str) -> str | None:
        """Fetch a single article and return its `<div class="text">` body."""
        assert self._client is not None
        r = await self._client.get(url)
        if r.status_code != 200 or len(r.text) < 1000:
            return None
        soup = BeautifulSoup(r.text, "lxml")
        text_div = soup.find("div", class_="text")
        if text_div is None:
            return None
        return text_div.get_text("\n", strip=True)


# ────────────── session pool ──────────────

# We cache one valid PHPSESSID per Python process. The real cost we want
# to avoid is the duplicate-session race: the steelnet site forces only
# one active login per account, so two back-to-back logins kick each other
# out and the second client ends up reading 110-byte member-only stubs.
_cached_cookies: dict[str, str] | None = None
_cookie_lock = asyncio.Lock()


async def _get_or_refresh_cookies(*, force: bool = False) -> dict[str, str]:
    global _cached_cookies
    async with _cookie_lock:
        if _cached_cookies is not None and not force:
            return _cached_cookies
        async with SteelnetClient() as sn:
            _cached_cookies = sn.get_cookies()
        return _cached_cookies


def invalidate_session() -> None:
    global _cached_cookies
    _cached_cookies = None


@asynccontextmanager
async def shared_session():
    """Yield a SteelnetClient that re-uses a cached PHPSESSID.

    Use this everywhere inside a single agent run. On `非會員只能看標題`
    detection, callers should call `invalidate_session()` and retry.
    """
    cookies = await _get_or_refresh_cookies()
    async with SteelnetClient(cached_cookies=cookies) as sn:
        yield sn


# ────────────── pure parsing helpers (no I/O) ──────────────

# "本週牌價：鋼筋18,900元、廢鋼9,900元，型鋼24,500元。"
# also handles "鋼筋 16400" without comma
_PRICE_LINE_RE = re.compile(
    r"鋼筋\s*([\d,]+)\s*元.*?廢鋼\s*([\d,]+)\s*元.*?型鋼\s*([\d,]+)\s*元",
    re.DOTALL,
)
# Fallback: just the single-number pattern
_REBAR_ONLY_RE = re.compile(r"鋼筋\s*([\d,]+)\s*元")
_SCRAP_ONLY_RE = re.compile(r"廢鋼\s*([\d,]+)\s*元")
_SECTION_ONLY_RE = re.compile(r"型鋼\s*([\d,]+)\s*元")

# "豐興今(4)日上午開出5月第一盤"  → day + month
# "豐興今(11)日上午開出週盤"      → day only (use fallback month)
_DATE_RE = re.compile(r"今\s*\(\s*(\d{1,2})\s*\)\s*日.*?(\d{1,2})\s*月", re.DOTALL)
_DATE_RE_REV = re.compile(r"(\d{1,2})\s*月.*?今\s*\(\s*(\d{1,2})\s*\)\s*日", re.DOTALL)
_DAY_ONLY_RE = re.compile(r"今\s*\(\s*(\d{1,2})\s*\)\s*日")

# International scrap paragraph marker: ANY line containing 國際 + (美國|日本|澳洲)
_INTL_HINTS = ("國際原料", "美國大船廢鋼", "美國貨櫃廢鋼", "日本H2", "日本2H", "澳洲鐵礦")


class FengxingArticleData:
    """Parsed result from a 豐興 weekly opening article."""

    sd280_price: int | None = None
    scrap_price: int | None = None
    section_price: int | None = None
    opening_paragraph: str = ""     # 1st content paragraph (price line)
    intl_scrap_paragraph: str = ""  # 2nd content paragraph (international)
    opening_date: date | None = None

    def __repr__(self) -> str:
        return (
            f"FengxingArticleData(SD280={self.sd280_price}, "
            f"廢鋼={self.scrap_price}, 型鋼={self.section_price}, "
            f"opening_date={self.opening_date})"
        )


def _parse_int(s: str) -> int:
    return int(s.replace(",", "").strip())


def _split_paragraphs(body: str) -> list[str]:
    """Split article body into paragraphs (lines), drop noise like 「記者...報導」."""
    raw = [line.strip() for line in body.split("\n") if line.strip()]
    return [p for p in raw if not p.startswith("記者") and len(p) > 10]


def parse_fengxing_opening_article(
    body: str,
    *,
    fallback_year: int | None = None,
    fallback_month: int | None = None,
) -> FengxingArticleData:
    """Extract structured data from a 豐興 weekly opening article body.

    `body` should be the inner text of `<div class="text">`, NOT the whole page.

    Returns a FengxingArticleData; any field stays None / "" if not found.
    """
    out = FengxingArticleData()
    paragraphs = _split_paragraphs(body)

    # Identify price paragraph and intl paragraph by content
    for p in paragraphs:
        if not out.opening_paragraph and ("本週牌價" in p or "牌價" in p):
            out.opening_paragraph = p
        elif not out.intl_scrap_paragraph and any(h in p for h in _INTL_HINTS):
            out.intl_scrap_paragraph = p

    # Fallback: first paragraph containing 鋼筋 + 元 = price line
    if not out.opening_paragraph:
        for p in paragraphs:
            if "鋼筋" in p and "元" in p:
                out.opening_paragraph = p
                break

    # Extract numbers from price paragraph
    if out.opening_paragraph:
        m = _PRICE_LINE_RE.search(out.opening_paragraph)
        if m:
            out.sd280_price = _parse_int(m.group(1))
            out.scrap_price = _parse_int(m.group(2))
            out.section_price = _parse_int(m.group(3))
        else:
            # Try one-by-one
            m_r = _REBAR_ONLY_RE.search(out.opening_paragraph)
            m_s = _SCRAP_ONLY_RE.search(out.opening_paragraph)
            m_t = _SECTION_ONLY_RE.search(out.opening_paragraph)
            if m_r:
                out.sd280_price = _parse_int(m_r.group(1))
            if m_s:
                out.scrap_price = _parse_int(m_s.group(1))
            if m_t:
                out.section_price = _parse_int(m_t.group(1))

    # Extract date — three patterns in priority order
    if out.opening_paragraph:
        year = fallback_year or date.today().year
        d_match = _DATE_RE.search(out.opening_paragraph)
        if d_match:
            day, month = int(d_match.group(1)), int(d_match.group(2))
            try:
                out.opening_date = date(year, month, day)
            except ValueError:
                pass
        else:
            d_match = _DATE_RE_REV.search(out.opening_paragraph)
            if d_match:
                month, day = int(d_match.group(1)), int(d_match.group(2))
                try:
                    out.opening_date = date(year, month, day)
                except ValueError:
                    pass
        # Day-only pattern (e.g. "今(11)日上午開出週盤" with no month)
        if out.opening_date is None:
            d_match = _DAY_ONLY_RE.search(out.opening_paragraph)
            if d_match and fallback_month:
                day = int(d_match.group(1))
                try:
                    out.opening_date = date(year, fallback_month, day)
                except ValueError:
                    pass

    return out


def parse_intl_scrap_prices(paragraph: str) -> dict[str, int | None]:
    """Pull individual USD/噸 prices out of the intl scrap sentence.

    Source format (from 豐興 weekly opening article):
      "上週美國大船廢鋼無報價，日本H2廢鋼上週報價上漲10美元至385美元，
       美國貨櫃廢鋼上週報價微漲1美元至363美元/噸，
       澳洲鐵礦砂上漲0.70美元至109.75美元/噸。"

    Returns dict with keys:
      "us_container_scrap"  美國貨櫃廢鋼  → int | None
      "jp2h_scrap"          日本 2H 廢鋼  → int | None
      "au_iron_ore"         澳洲鐵礦砂   → float | None  (kept as int rounded)

    None means "無報價" / "未開盤" / pattern not found for that topic.
    """
    if not paragraph:
        return {"us_container_scrap": None, "jp2h_scrap": None, "au_iron_ore": None}

    # Split into clauses on commas / semicolons / periods
    # so we don't accidentally pull a number from a different topic.
    clauses = re.split(r"[，,。；;]", paragraph)

    # Strip parenthetical context like "(先前為300美元)" / "(前週報價上漲10美元)"
    # Those refer to PRIOR weeks, not the current price.
    _paren = re.compile(r"[(（][^)）]*[)）]")

    def _extract(keywords: tuple[str, ...]) -> int | None:
        """Find a clause matching keywords; return its USD price or None."""
        for c in clauses:
            if not any(kw in c for kw in keywords):
                continue
            # Check for "no quote" markers — but skip them if they're inside
            # the parenthetical (we strip those next)
            outside_paren = _paren.sub("", c)
            if any(no in outside_paren for no in ("無報價", "未開盤", "沒報價")):
                return None
            # Take the LAST 美元 number outside parentheses
            # ("上漲X美元至Y美元/噸" → Y; "持平為Y美元" → Y; "上漲至Y美元" → Y)
            matches = re.findall(r"(\d+(?:\.\d+)?)\s*美元", outside_paren)
            if matches:
                try:
                    return int(round(float(matches[-1])))
                except ValueError:
                    pass
        return None

    return {
        "us_container_scrap": _extract(("美國貨櫃廢鋼", "美貨櫃")),
        "jp2h_scrap":         _extract(("日本2H", "日本 2H", "日本H2", "日本 H2", "日本2H廢鋼")),
        "au_iron_ore":        _extract(("澳洲鐵礦砂", "澳洲鐵礦", "澳礦")),
    }


def polish_intl_scrap(raw: str, target_date: date) -> str:
    """Light text fixes — make article tense ("上週") read naturally as
    "本週" for the meeting record. Not a full LLM rewrite.
    """
    _ = target_date
    polished = raw
    polished = polished.replace("上週報價微漲", "本週上漲")
    polished = polished.replace("上週報價上漲", "本週上漲")
    polished = polished.replace("上週報價下跌", "本週下跌")
    polished = polished.replace("上週沒報價", "本週無報價")
    polished = polished.replace("上週無報價", "本週無報價")
    polished = polished.replace("(前週", "(上週")
    polished = polished.replace("H2廢鋼", "2H 廢鋼")  # match PDF "日本 2H"
    return polished

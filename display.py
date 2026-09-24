"""Pure helpers for turning data into safe, display-ready values (no Streamlit here)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping
from urllib.parse import quote

import pandas as pd

from .config import CATEGORIES, OTHER_CATEGORY, Stock
from .news import NewsItem, safe_link
from .prices import Quote

IST = timezone(timedelta(hours=5, minutes=30))   # fixed offset: no tz database needed on Windows
CATEGORY_LABELS = {cid: label for cid, label, _ in CATEGORIES} | {OTHER_CATEGORY[0]: OTHER_CATEGORY[1]}
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def escape_md(text: str | None) -> str:
    """Neutralise Markdown, LaTeX ($) and Streamlit colour directives (:red[...]) in feed text."""
    return _MD_SPECIAL.sub(r"\\\1", text or "")


def md_link(title: str, url: str) -> str:
    link = safe_link(url)
    if not link:
        return escape_md(title)
    link = link.replace("(", "%28").replace(")", "%29")
    return f"[{escape_md(title)}]({link})"


def to_ist(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def day_label(dt: datetime | None, today: datetime | None = None) -> str:
    local = to_ist(dt)
    if local is None:
        return "Date unknown"
    today_local = (to_ist(today) or datetime.now(IST)).date()
    if local.date() == today_local:
        return "Today"
    if local.date() == today_local - timedelta(days=1):
        return "Yesterday"
    return local.strftime("%a %d %b %Y")


def time_label(dt: datetime | None) -> str:
    local = to_ist(dt)
    return local.strftime("%H:%M IST") if local else ""


def nse_url(symbol: str) -> str:
    return "https://www.nseindia.com/get-quotes/equity?symbol=" + quote(symbol, safe="")


def filter_news(
    items: Iterable[NewsItem],
    categories: Iterable[str] | None = None,
    query: str = "",
    ticker: str | None = None,
) -> list[NewsItem]:
    cats = set(categories or ())
    q = (query or "").strip().lower()
    out = []
    for item in items:
        if cats and item.category not in cats:
            continue
        if ticker and ticker not in item.tickers:
            continue
        if q and q not in f"{item.title} {item.summary} {item.source}".lower():
            continue
        out.append(item)
    return out


def quotes_frame(stocks: Iterable[Stock], quotes: Mapping[str, Quote]) -> pd.DataFrame:
    rows = []
    for s in stocks:
        q = quotes.get(s.symbol) or Quote(s.symbol, error="Not fetched")
        rows.append({
            "Symbol": s.symbol,
            "Company": s.name,
            "Segment": s.segment,
            "Price (₹)": q.last,
            "Change %": q.change_pct,
            "52W high": q.high_52w,
            "Off 52W high %": q.off_high_pct,
            "3M trend": list(q.trend),
            "As of": q.as_of.strftime("%d %b") if q.as_of is not None else "",
            "Status": q.error or "OK",
            "NSE": nse_url(s.symbol),
        })
    return pd.DataFrame(rows)


def breadth(quotes: Mapping[str, Quote]) -> tuple[int, int, int]:
    up = down = flat = 0
    for q in quotes.values():
        pct = q.change_pct
        if pct is None:
            continue
        if pct > 0.005:
            up += 1
        elif pct < -0.005:
            down += 1
        else:
            flat += 1
    return up, down, flat


# ---------- official tab ----------

def official_kind_labels() -> dict[str, str]:
    from .config import OFFICIAL_KINDS, OFFICIAL_OTHER
    return {kid: label for kid, label, _ in OFFICIAL_KINDS} | {OFFICIAL_OTHER[0]: OFFICIAL_OTHER[1]}


def filter_official(items, bodies=None, kinds=None, query: str = ""):
    bodies, kinds = set(bodies or ()), set(kinds or ())
    q = (query or "").strip().lower()
    return [
        a for a in items
        if (not bodies or a.body in bodies)
        and (not kinds or a.kind in kinds)
        and (not q or q in a.title.lower())
    ]


def date_label(d) -> str:
    return d.strftime("%a %d %b %Y") if d else "Date unknown"


def is_recent(d, today=None, days: int = 7) -> bool:
    if not d:
        return False
    today = today or datetime.now(IST).date()
    return timedelta(0) <= today - d <= timedelta(days=days)

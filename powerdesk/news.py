"""Power-sector news from RSS feeds.

Design rule: one broken feed never breaks the page. fetch_news always returns
(items, errors); errors holds one human-readable line per feed that failed.
"""
from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Iterable

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import (
    CATEGORIES, HTTP_TIMEOUT, HTTP_WORKERS, NEWS_MAX_AGE_DAYS, NEWS_MAX_ITEMS,
    OTHER_CATEGORY, USER_AGENT, Feed, Stock,
)

log = logging.getLogger(__name__)
MAX_FEED_BYTES = 5_000_000
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_LINK_RE = re.compile(r"^https?://[^\s<>\"'`]+$", re.IGNORECASE)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published: datetime | None
    summary: str
    category: str
    tickers: tuple[str, ...]


# ---------- text helpers ----------

def clean_text(value: Any, limit: int = 400) -> str:
    """Strip HTML and collapse whitespace; always returns a str."""
    if not isinstance(value, str):
        return ""
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(value))).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut) + "…"


def safe_link(value: Any) -> str:
    """Return the URL only if it is a plain http(s) link; otherwise ''."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if _LINK_RE.match(value) else ""


@lru_cache(maxsize=256)
def _phrase_pattern(terms: tuple[str, ...]) -> re.Pattern[str] | None:
    """Whole-phrase matcher: 'iex' matches 'IEX shares' but not 'sciex'."""
    terms = tuple(t.lower() for t in terms if t)
    if not terms:
        return None
    alts = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])(?:{alts})(?![a-z0-9])")


def classify(text: str) -> str:
    low = text.lower() if isinstance(text, str) else ""
    for cid, _label, words in CATEGORIES:
        pattern = _phrase_pattern(tuple(words))
        if pattern and pattern.search(low):
            return cid
    return OTHER_CATEGORY[0]


def tag_stocks(text: str, stocks: Iterable[Stock]) -> tuple[str, ...]:
    low = text.lower() if isinstance(text, str) else ""
    found = []
    for stock in stocks:
        pattern = _phrase_pattern(stock.match_terms)
        if pattern and pattern.search(low):
            found.append(stock.symbol)
    return tuple(found)


def dedupe_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())[:80]


# ---------- parsing ----------

def _published(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime(*tuple(value)[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def parse_feed(content: bytes, feed_name: str, stocks: Iterable[Stock]) -> list[NewsItem]:
    stocks = list(stocks)
    parsed = feedparser.parse(content)
    items: list[NewsItem] = []
    for entry in parsed.get("entries") or []:
        if not hasattr(entry, "get"):
            continue
        title = clean_text(entry.get("title"), 300)
        link = safe_link(entry.get("link"))
        if not title or not link:
            continue
        source_meta = entry.get("source")
        source = ""
        if hasattr(source_meta, "get"):
            source = clean_text(source_meta.get("title"), 80)
        source = source or feed_name
        suffix = f" - {source}"
        if title.endswith(suffix) and len(title) > len(suffix):  # Google News appends the publisher
            title = title[: -len(suffix)].strip()
        summary = clean_text(entry.get("summary"))
        s_low, t_low = summary.lower(), title.lower()
        if summary and (t_low.startswith(s_low[:60]) or s_low.startswith(t_low[:40])):
            summary = ""  # Google News summaries often just repeat the headline
        text = f"{title} {summary}"
        items.append(NewsItem(
            title=title, link=link, source=source, published=_published(entry),
            summary=summary, category=classify(text), tickers=tag_stocks(text, stocks),
        ))
    return items


# ---------- fetching ----------

def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=0.8, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET"}))
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = USER_AGENT
    return session


def _download(session: Any, url: str) -> bytes:
    with session.get(url, timeout=HTTP_TIMEOUT, stream=True) as resp:
        resp.raise_for_status()
        chunks, size = [], 0
        for chunk in resp.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_FEED_BYTES:
                raise ValueError("feed larger than 5 MB")
            chunks.append(chunk)
    return b"".join(chunks)


def fetch_news(
    feeds: Iterable[Feed],
    stocks: Iterable[Stock],
    session: Any = None,
    now: datetime | None = None,
) -> tuple[list[NewsItem], list[str]]:
    feeds, stocks = list(feeds), list(stocks)
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=NEWS_MAX_AGE_DAYS)

    def one(feed: Feed) -> tuple[list[NewsItem], str | None]:
        try:
            return parse_feed(_download(session, feed.url), feed.name, stocks), None
        except Exception as exc:
            log.warning("Feed %s failed: %r", feed.name, exc)
            return [], f"{feed.name}: {type(exc).__name__}"

    results: list[tuple[list[NewsItem], str | None]] = []
    if feeds:
        own_session = session is None
        session = session or make_session()
        try:
            with ThreadPoolExecutor(max_workers=max(1, min(HTTP_WORKERS, len(feeds)))) as pool:
                results = list(pool.map(one, feeds))
        finally:
            if own_session:
                session.close()

    errors = [err for _, err in results if err]
    seen: set[str] = set()
    merged: list[NewsItem] = []
    for batch, _ in results:
        for item in batch:
            key = dedupe_key(item.title)
            if not key or key in seen:
                continue
            if item.published and item.published < cutoff:
                continue
            seen.add(key)
            merged.append(item)

    merged.sort(key=lambda i: i.published or _EPOCH, reverse=True)
    return merged[:NEWS_MAX_ITEMS], errors

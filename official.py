"""Official announcements: CEA and MNRE notice pages, plus PIB press releases.

Government sites rarely offer feeds, so their notice pages are read directly.
The reader is deliberately generic: it looks at every table row (or list item),
takes the longest-looking title, the first real date and the first real link.
That way a cosmetic redesign doesn't break it; only a page with no rows at all would.

Design rule, same as news: one failing source never breaks the tab.
fetch_official always returns (items, errors).
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .config import (
    HTTP_WORKERS, OFFICIAL_KINDS, OFFICIAL_MAX_AGE_DAYS, OFFICIAL_MAX_ITEMS, OFFICIAL_NOISE,
    OFFICIAL_OTHER, Feed, OfficialPage,
)
from .news import _phrase_pattern, clean_text, dedupe_key, download, make_session, parse_feed, safe_link

log = logging.getLogger(__name__)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DMY = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_D_MON_Y = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]{3,9})[,\s-]+(\d{4})\b")
_MON_D_Y = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
_SIZE_SUFFIX = re.compile(r"\s*\((?:[^()]*\b(?:kb|mb)\b[^()]*)\)\s*$", re.IGNORECASE)
_NOISE = _phrase_pattern(tuple(OFFICIAL_NOISE))


@dataclass(frozen=True)
class Announcement:
    title: str
    link: str
    body: str                 # CEA, MNRE, PIB: Ministry of Power, ...
    published: date | None
    kind: str


# ---------- helpers ----------

def _make_date(y: int, m: int, d: int) -> date | None:
    try:
        result = date(y, m, d)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if 2000 <= result.year <= 2100 else None


def find_date(text: str) -> date | None:
    """First valid date in the text, in any of the formats Indian government sites use."""
    if not isinstance(text, str) or not text:
        return None
    candidates: list[tuple[int, date]] = []
    for m in _ISO.finditer(text):
        if (d := _make_date(int(m[1]), int(m[2]), int(m[3]))):
            candidates.append((m.start(), d))
    for m in _DMY.finditer(text):
        if (d := _make_date(int(m[3]), int(m[2]), int(m[1]))):
            candidates.append((m.start(), d))
    for m in _D_MON_Y.finditer(text):
        month = MONTHS.get(m[2][:3].lower())
        if month and (d := _make_date(int(m[3]), month, int(m[1]))):
            candidates.append((m.start(), d))
    for m in _MON_D_Y.finditer(text):
        month = MONTHS.get(m[1][:3].lower())
        if month and (d := _make_date(int(m[3]), month, int(m[2]))):
            candidates.append((m.start(), d))
    return min(candidates)[1] if candidates else None


def classify_official(title: str) -> str:
    low = title.lower() if isinstance(title, str) else ""
    for kid, _label, words in OFFICIAL_KINDS:
        pattern = _phrase_pattern(tuple(words))
        if pattern and pattern.search(low):
            return kid
    return OFFICIAL_OTHER[0]


def is_noise(title: str) -> bool:
    return bool(_NOISE and _NOISE.search(title.lower()))


def _date_only(text: str) -> bool:
    rest = text
    for rx in (_ISO, _DMY, _D_MON_Y, _MON_D_Y):
        rest = rx.sub(" ", rest)
    return len(re.sub(r"[\W_]+", "", rest)) < 5


def _looks_like_title(text: str) -> bool:
    if len(text) < 15 or not re.search(r"[A-Za-z]{3}", text):
        return False
    if text.lower().startswith(("http://", "https://", "view", "download")):
        return False
    return True


def _resolve_link(href: Any, base_url: str) -> str:
    if not isinstance(href, str):
        return ""
    href = href.strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return ""
    try:
        absolute = urljoin(base_url, href)
    except ValueError:
        return ""
    return safe_link(absolute.replace(" ", "%20"))


# ---------- parsing a notice page ----------

def parse_listing(content: bytes, base_url: str, body: str) -> list[Announcement]:
    soup = BeautifulSoup(content or b"", "html.parser")
    rows = [r for r in soup.find_all("tr") if r.find("td")]
    from_list = not rows
    if from_list:  # no tables: fall back to list items, but only dated ones (skips menus)
        rows = soup.find_all("li")

    items: list[Announcement] = []
    for row in rows:
        cells = row.find_all("td") or [row]
        texts = [clean_text(c.get_text(" "), 500) for c in cells]

        title_idx = next((i for i, t in enumerate(texts) if _looks_like_title(t) and not _date_only(t)), None)
        if title_idx is None:
            continue
        title = _SIZE_SUFFIX.sub("", texts[title_idx]).strip()
        if not _looks_like_title(title) or is_noise(title):
            continue

        other_text = " ".join(t for i, t in enumerate(texts) if i != title_idx)
        published = find_date(other_text) or find_date(title)
        if from_list and published is None:
            continue

        link = ""
        for a in row.find_all("a", href=True):
            link = _resolve_link(a.get("href"), base_url)
            if link:
                break
        if not link:
            continue

        items.append(Announcement(title=clean_text(title, 300), link=link, body=body,
                                  published=published, kind=classify_official(title)))
    return items


def _from_feed(content: bytes, feed: Feed) -> list[Announcement]:
    out = []
    for n in parse_feed(content, feed.name, ()):
        if is_noise(n.title):
            continue
        out.append(Announcement(
            title=n.title, link=n.link, body=feed.name,
            published=n.published.date() if n.published else None,
            kind=classify_official(n.title),
        ))
    return out


# ---------- fetching ----------

def fetch_official(
    pages: Iterable[OfficialPage],
    feeds: Iterable[Feed],
    session: Any = None,
    today: date | None = None,
) -> tuple[list[Announcement], list[str]]:
    jobs: list[tuple[str, str, Any]] = [(p.body, p.url, p) for p in pages] + [(f.name, f.url, f) for f in feeds]
    today = today or datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=OFFICIAL_MAX_AGE_DAYS)

    def one(job: tuple[str, str, Any]) -> tuple[list[Announcement], str | None]:
        name, url, src = job
        try:
            content = download(session, url)
            items = _from_feed(content, src) if isinstance(src, Feed) else parse_listing(content, url, src.body)
            if not items and not isinstance(src, Feed):
                return [], f"{name}: page loaded but no notices were found (the site layout may have changed)"
            return items, None
        except Exception as exc:
            log.warning("Official source %s failed: %r", name, exc)
            return [], f"{name}: {type(exc).__name__}"

    results: list[tuple[list[Announcement], str | None]] = []
    if jobs:
        own_session = session is None
        session = session or make_session()
        try:
            with ThreadPoolExecutor(max_workers=max(1, min(HTTP_WORKERS, len(jobs)))) as pool:
                results = list(pool.map(one, jobs))
        finally:
            if own_session:
                session.close()

    errors = [e for _, e in results if e]
    seen: set[str] = set()
    merged: list[Announcement] = []
    for batch, _ in results:
        for item in batch:
            key = dedupe_key(item.title)
            if not key or key in seen:
                continue
            if item.published and (item.published < cutoff or item.published > today + timedelta(days=2)):
                continue
            seen.add(key)
            merged.append(item)

    merged.sort(key=lambda a: a.published or date.min, reverse=True)
    return merged[:OFFICIAL_MAX_ITEMS], errors

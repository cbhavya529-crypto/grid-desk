from datetime import datetime, timedelta, timezone

import pytest
import requests

from powerdesk.config import WATCHLIST, Feed
from powerdesk.news import (
    classify, clean_text, dedupe_key, fetch_news, parse_feed, safe_link, tag_stocks,
)

NOW = datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc)

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>t</title>
<item><title>NTPC REL invites bids for wind project in Andhra Pradesh - Mercom India</title>
  <link>https://example.com/a</link><source url="https://mercom">Mercom India</source>
  <pubDate>Mon, 21 Sep 2026 10:00:00 GMT</pubDate>
  <description>&lt;a href="x"&gt;NTPC REL invites bids for wind project&lt;/a&gt;</description></item>
<item><title>Tata Power Mundra directive extended</title><link>https://example.com/b</link>
  <pubDate>Tue, 22 Sep 2026 10:00:00 GMT</pubDate><description>Plant &lt;b&gt;keeps&lt;/b&gt; running.</description></item>
<item><title>No link here</title></item>
<item><title>Bad scheme</title><link>javascript:alert(1)</link></item>
<item><title>Undated story about a 50 MW solar plant</title><link>https://example.com/c</link></item>
<item><title>Ancient news about a 10 MW plant</title><link>https://example.com/d</link>
  <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate></item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, content=b"", status=200):
        self.content, self.status = content, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status}")

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]


class FakeSession:
    def __init__(self, routes):
        self.routes = routes

    def get(self, url, **kwargs):
        result = self.routes[url]
        if isinstance(result, Exception):
            raise result
        return result


def test_parse_feed_cleans_and_filters():
    items = parse_feed(RSS, "Test", WATCHLIST)
    titles = [i.title for i in items]
    assert "NTPC REL invites bids for wind project in Andhra Pradesh" in titles  # publisher suffix removed
    assert "No link here" not in titles
    assert "Bad scheme" not in titles                                          # non-http link dropped
    first = items[0]
    assert first.source == "Mercom India"
    assert first.summary == ""                                                 # summary repeating title dropped
    assert first.category == "tender"
    assert set(first.tickers) >= {"NTPCGREEN", "NTPC"}
    tata = next(i for i in items if i.title.startswith("Tata Power"))
    assert tata.category == "tata" and "TATAPOWER" in tata.tickers
    assert tata.summary == "Plant keeps running."


def test_parse_feed_survives_garbage():
    assert parse_feed(b"not xml at all <<<", "X", WATCHLIST) == []
    assert parse_feed(b"", "X", WATCHLIST) == []


def test_fetch_news_isolates_failures_dedupes_and_sorts():
    routes = {
        "u1": FakeResponse(RSS),
        "u2": FakeResponse(RSS),                      # duplicate content
        "u3": requests.ConnectionError("down"),
        "u4": FakeResponse(status=503),
    }
    feeds = [Feed("One", "u1"), Feed("Two", "u2"), Feed("Three", "u3"), Feed("Four", "u4")]
    items, errors = fetch_news(feeds, WATCHLIST, session=FakeSession(routes), now=NOW)
    assert len(errors) == 2 and any("Three" in e for e in errors) and any("Four" in e for e in errors)
    keys = [dedupe_key(i.title) for i in items]
    assert len(keys) == len(set(keys))
    assert all("Ancient" not in i.title for i in items)            # older than max age
    dated = [i.published for i in items if i.published]
    assert dated == sorted(dated, reverse=True)
    assert items[-1].published is None                               # undated last


def test_fetch_news_all_fail_returns_empty():
    items, errors = fetch_news([Feed("A", "a")], WATCHLIST, session=FakeSession({"a": TimeoutError()}), now=NOW)
    assert items == [] and len(errors) == 1


def test_fetch_news_no_feeds():
    assert fetch_news([], WATCHLIST, now=NOW) == ([], [])


def test_oversized_feed_rejected():
    big = FakeResponse(b"x" * 6_000_000)
    items, errors = fetch_news([Feed("Big", "b")], WATCHLIST, session=FakeSession({"b": big}), now=NOW)
    assert items == [] and "Big" in errors[0]


@pytest.mark.parametrize("text,expected", [
    ("SECI issues tender for 2 GW solar", "tender"),
    ("CERC proposes grid code amendments", "policy"),
    ("Power Grid shares rise 3%", "markets"),
    ("Buxar thermal power project unit commissioned by government", "govt"),
    ("Juniper inaugurates 90 MW wind site", "private"),
    ("Weather outlook for monsoon", "other"),
    ("Tata Power wins 200 MW bid", "tata"),
])
def test_classify(text, expected):
    assert classify(text) == expected


def test_tagging_uses_whole_words():
    assert tag_stocks("IEX volumes jump", WATCHLIST) == ("IEX",)
    assert tag_stocks("Sciex launches lab device", WATCHLIST) == ()
    assert "POWERGRID" in tag_stocks("POWERGRID to raise bonds", WATCHLIST)
    assert tag_stocks(None, WATCHLIST) == ()


def test_text_helpers():
    assert clean_text(None) == ""
    assert clean_text("<p>a&amp;b</p>   c") == "a&b c"
    long = clean_text("word " * 200, limit=50)
    assert len(long) <= 50 and long.endswith("…")
    assert clean_text("x" * 100, limit=10).endswith("…")
    assert safe_link("https://ok.com/a?b=1") == "https://ok.com/a?b=1"
    for bad in ("javascript:alert(1)", "ftp://x", "https://a.com/\"onmouseover", None, 5, ""):
        assert safe_link(bad) == ""

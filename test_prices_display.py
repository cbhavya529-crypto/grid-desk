import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from powerdesk.config import Stock, WATCHLIST
from powerdesk.display import breadth, day_label, escape_md, filter_news, md_link, quotes_frame
from powerdesk.news import NewsItem
from powerdesk.prices import Quote, fetch_quotes, quote_from_closes

A = Stock("AAA", "Alpha", "Seg")
B = Stock("BBB", "Beta", "Seg")
DATES = pd.date_range("2025-09-01", periods=300, freq="B")


def multi_frame(data: dict[str, list[float]], ticker_first=True) -> pd.DataFrame:
    cols = {}
    for ticker, closes in data.items():
        for field in ("Open", "Close"):
            key = (ticker, field) if ticker_first else (field, ticker)
            cols[key] = closes
    return pd.DataFrame(cols, index=DATES[: len(next(iter(data.values())))])


def test_multiindex_both_layouts():
    closes = list(np.linspace(100, 130, 300))
    for layout in (True, False):
        frame = multi_frame({"AAA.NS": closes, "BBB.NS": closes}, ticker_first=layout)
        quotes = fetch_quotes([A, B], download=lambda *a, **k: frame)
        q = quotes["AAA"]
        assert q.error is None
        assert q.last == pytest.approx(130)
        assert q.change_pct == pytest.approx((130 - closes[-2]) / closes[-2] * 100)
        assert len(q.trend) == 66


def test_missing_ticker_and_bad_values():
    frame = multi_frame({"AAA.NS": [float("nan"), 0, -5, 101, float("inf"), 102]})
    quotes = fetch_quotes([A, B], download=lambda *a, **k: frame)
    assert quotes["AAA"].last == 102 and quotes["AAA"].prev_close == 101
    assert quotes["BBB"].error == "No data returned"


def test_download_exception_never_raises():
    def boom(*a, **k):
        raise ConnectionError("rate limited")
    quotes = fetch_quotes(WATCHLIST, download=boom)
    assert len(quotes) == len(WATCHLIST)
    assert all(q.error and "ConnectionError" in q.error for q in quotes.values())


@pytest.mark.parametrize("result", [None, pd.DataFrame(), "garbage", 42])
def test_weird_download_results(result):
    quotes = fetch_quotes([A, B], download=lambda *a, **k: result)
    assert all(q.error for q in quotes.values())


def test_single_ticker_flat_frame():
    frame = pd.DataFrame({"Close": [10.0, 11.0]}, index=DATES[:2])
    assert fetch_quotes([A], download=lambda *a, **k: frame)["AAA"].last == 11.0
    # a flat frame with two tickers requested is ambiguous and must not be guessed
    assert fetch_quotes([A, B], download=lambda *a, **k: frame)["AAA"].error


def test_quote_edge_cases():
    q = quote_from_closes("X", pd.Series([50.0]))
    assert q.last == 50 and q.prev_close is None and q.change_pct is None and q.as_of is None
    assert quote_from_closes("X", pd.Series(["a", None])).error == "No valid prices"
    assert Quote("X", last=10, prev_close=0).change_pct is None
    assert Quote("X", last=10, high_52w=0).off_high_pct is None


def test_empty_watchlist():
    assert fetch_quotes([], download=lambda *a, **k: 1 / 0) == {}


def test_quotes_frame_and_breadth():
    quotes = {"AAA": Quote("AAA", last=11, prev_close=10), "BBB": Quote("BBB", error="No data returned")}
    frame = quotes_frame([A, B, Stock("CCC", "C", "S")], quotes)
    assert list(frame["Status"]) == ["OK", "No data returned", "Not fetched"]
    assert math.isnan(frame.loc[1, "Price (₹)"]) or frame.loc[1, "Price (₹)"] is None
    assert breadth(quotes) == (1, 0, 0)


def test_markdown_escaping():
    evil = "Profit *up* [click](javascript:x) $x^2$ :red[alert] #1"
    out = escape_md(evil)
    for ch in "*[]()$#:":
        assert f"\\{ch}" in out
    assert escape_md(None) == ""
    assert md_link("t", "javascript:alert(1)") == "t"
    assert md_link("t", "https://a.com/x_(1)") == "[t](https://a.com/x_%281%29)"


def test_filter_and_day_labels():
    now = datetime(2026, 9, 24, 6, tzinfo=timezone.utc)
    items = [
        NewsItem("SECI tender", "https://a", "S", now, "", "tender", ("NTPC",)),
        NewsItem("Policy note", "https://b", "S", None, "grid code", "policy", ()),
    ]
    assert len(filter_news(items)) == 2
    assert [i.title for i in filter_news(items, ["policy"])] == ["Policy note"]
    assert [i.title for i in filter_news(items, query="GRID")] == ["Policy note"]
    assert [i.title for i in filter_news(items, ticker="NTPC")] == ["SECI tender"]
    assert day_label(now, today=now) == "Today"
    assert day_label(None) == "Date unknown"
    assert day_label(datetime(2026, 9, 23, 20, tzinfo=timezone.utc), today=now) == "Today"  # 01:30 IST on the 24th

"""Grid Desk — live power-sector stocks and news.

Run:  streamlit run app.py
"""
from __future__ import annotations

import logging
from itertools import groupby

import streamlit as st

from powerdesk import config
from powerdesk.display import (
    CATEGORY_LABELS, breadth, day_label, escape_md, filter_news, md_link,
    quotes_frame, time_label,
)
from powerdesk.news import fetch_news
from powerdesk.prices import fetch_quotes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("griddesk")

st.set_page_config(page_title="Grid Desk", page_icon="⚡", layout="wide")


# ---------- data (cached; the fetchers themselves never raise) ----------

@st.cache_data(ttl=config.PRICE_TTL_SECONDS, show_spinner=False)
def load_quotes():
    return fetch_quotes(config.WATCHLIST)


@st.cache_data(ttl=config.NEWS_TTL_SECONDS, show_spinner=False)
def load_news():
    return fetch_news(config.FEEDS, config.WATCHLIST)


def guarded(title: str):
    """Last line of defence: a failing section shows a message instead of taking the app down."""
    def wrap(fn):
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception:
                log.exception("%s failed", title)
                st.error(f"{title} hit an unexpected error. Press “Refresh now”; details are in the terminal log.")
        return inner
    return wrap


# ---------- header ----------

left, right = st.columns([4, 1], vertical_alignment="bottom")
with left:
    st.title("⚡ Grid Desk")
    st.caption("Power sector stocks and news: tenders, government and private projects, policy, and deals.")
with right:
    if st.button("Refresh now", width="stretch"):
        load_quotes.clear()
        load_news.clear()
        st.rerun()

news_tab, stocks_tab = st.tabs(["News", "Stocks"])


# ---------- stocks ----------

@st.fragment(run_every=config.PRICE_TTL_SECONDS)
@guarded("Stocks")
def stocks_view():
    with st.spinner("Fetching prices…"):
        quotes = load_quotes()

    up, down, flat = breadth(quotes)
    failed = sum(1 for q in quotes.values() if q.error)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Advancing", up)
    c2.metric("Declining", down)
    c3.metric("Unchanged", flat)
    c4.metric("No data", failed)

    segments = sorted({s.segment for s in config.WATCHLIST})
    picked = st.multiselect("Segments", segments, default=segments, key="segments")
    stocks = [s for s in config.WATCHLIST if s.segment in picked]
    if not stocks:
        st.info("Pick at least one segment to see stocks.")
        return

    frame = quotes_frame(stocks, quotes)
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config={
            "Price (₹)": st.column_config.NumberColumn(format="%.2f"),
            "Change %": st.column_config.NumberColumn(format="%+.2f%%"),
            "52W high": st.column_config.NumberColumn(format="%.2f"),
            "Off 52W high %": st.column_config.NumberColumn(format="%.1f%%"),
            "3M trend": st.column_config.LineChartColumn(width="small"),
            "NSE": st.column_config.LinkColumn(display_text="Quote"),
        },
    )
    if failed:
        st.caption(f"{failed} stock(s) returned no data. Check the symbol in powerdesk/config.py, or Yahoo may be rate-limiting; it tries again on the next refresh.")
    st.caption(f"Prices from Yahoo Finance, about 15 minutes delayed. Updates every {config.PRICE_TTL_SECONDS // 60} minutes.")


# ---------- news ----------

@st.fragment(run_every=config.NEWS_TTL_SECONDS)
@guarded("News")
def news_view():
    with st.spinner("Fetching news…"):
        items, errors = load_news()

    cat_ids = [cid for cid, _, _ in config.CATEGORIES] + [config.OTHER_CATEGORY[0]]
    chosen = st.pills(
        "Categories", cat_ids, selection_mode="multi", key="cats",
        format_func=lambda cid: CATEGORY_LABELS.get(cid, cid),
    ) or []
    col_q, col_t = st.columns([3, 2])
    query = col_q.text_input("Search", placeholder="Company, state, MW, scheme…", key="q")
    symbols = ["All companies"] + [s.symbol for s in config.WATCHLIST]
    ticker = col_t.selectbox("Company", symbols, key="ticker")
    ticker = None if ticker == "All companies" else ticker

    shown = filter_news(items, chosen, query, ticker)
    st.caption(f"{len(shown)} of {len(items)} stories from the last {config.NEWS_MAX_AGE_DAYS} days. Updates every {config.NEWS_TTL_SECONDS // 60} minutes.")

    if not items:
        st.warning("No news loaded. Check your internet connection, then press “Refresh now”.")
    elif not shown:
        st.info("No stories match these filters. Clear the search or pick other categories.")

    for day, group in groupby(shown[:200], key=lambda i: day_label(i.published)):
        st.subheader(day, divider="gray")
        for item in group:
            meta = [CATEGORY_LABELS.get(item.category, item.category), item.source, time_label(item.published)]
            if item.tickers:
                meta.append(", ".join(item.tickers))
            body = f"**{md_link(item.title, item.link)}**"
            if item.summary:
                body += "  \n" + escape_md(item.summary)
            st.markdown(body)
            st.caption(escape_md(" · ".join(m for m in meta if m)))

    if errors:
        with st.expander(f"{len(errors)} source(s) didn’t load this time"):
            for err in errors:
                st.text(err)


with news_tab:
    news_view()
with stocks_tab:
    stocks_view()

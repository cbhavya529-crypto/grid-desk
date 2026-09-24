"""Stock quotes from Yahoo Finance (NSE, about 15 minutes delayed).

Design rule: nothing in here raises. Every stock always gets a Quote back;
if its data is missing or bad, the Quote carries an `error` string instead.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable

import pandas as pd

from .config import PRICE_PERIOD, TREND_POINTS, Stock

log = logging.getLogger(__name__)

PRICE_FIELDS = ("Close", "Adj Close")


@dataclass(frozen=True)
class Quote:
    symbol: str
    last: float | None = None
    prev_close: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    as_of: pd.Timestamp | None = None
    trend: tuple[float, ...] = ()
    error: str | None = None

    @property
    def change(self) -> float | None:
        if self.last is None or self.prev_close is None:
            return None
        return self.last - self.prev_close

    @property
    def change_pct(self) -> float | None:
        if self.change is None or not self.prev_close:
            return None
        return self.change / self.prev_close * 100

    @property
    def off_high_pct(self) -> float | None:
        if self.last is None or not self.high_52w:
            return None
        return (self.last - self.high_52w) / self.high_52w * 100


def _first_column(col: Any) -> pd.Series | None:
    if isinstance(col, pd.DataFrame):
        return col.iloc[:, 0] if col.shape[1] else None
    return col if isinstance(col, pd.Series) else None


def _extract_closes(frame: Any, ticker: str, allow_flat: bool) -> pd.Series | None:
    """Pull one ticker's close series out of whatever shape yfinance returned."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    cols = frame.columns
    if isinstance(cols, pd.MultiIndex):
        for level in range(cols.nlevels):
            if ticker in cols.get_level_values(level):
                sub = frame.xs(ticker, axis=1, level=level, drop_level=True)
                if not isinstance(sub, pd.DataFrame):
                    return None
                for field in PRICE_FIELDS:
                    if field in sub.columns:
                        return _first_column(sub[field])
        return None
    if allow_flat:  # a flat frame is only unambiguous when one ticker was requested
        for field in PRICE_FIELDS:
            if field in cols:
                return _first_column(frame[field])
    return None


def _is_good_price(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def quote_from_closes(symbol: str, closes: pd.Series | None) -> Quote:
    if closes is None:
        return Quote(symbol, error="No data returned")
    series = pd.to_numeric(closes, errors="coerce").astype("float64")
    series = series[series.map(_is_good_price)]
    if series.empty:
        return Quote(symbol, error="No valid prices")

    if isinstance(series.index, pd.DatetimeIndex):
        series = series[~series.index.duplicated(keep="last")].sort_index()
        year = series[series.index >= series.index[-1] - pd.Timedelta(days=365)]
        as_of = series.index[-1]
    else:
        year, as_of = series, None

    return Quote(
        symbol=symbol,
        last=float(series.iloc[-1]),
        prev_close=float(series.iloc[-2]) if len(series) > 1 else None,
        high_52w=float(year.max()),
        low_52w=float(year.min()),
        as_of=as_of,
        trend=tuple(float(v) for v in series.tail(TREND_POINTS)),
    )


def fetch_quotes(
    stocks: Iterable[Stock],
    download: Callable[..., Any] | None = None,
) -> dict[str, Quote]:
    stocks = list(stocks)
    if not stocks:
        return {}
    batch_error = None
    frame = None
    try:
        if download is None:
            import yfinance as yf
            download = yf.download
        frame = download(
            [s.yahoo for s in stocks], period=PRICE_PERIOD, interval="1d", group_by="ticker",
            auto_adjust=False, progress=False, threads=True, timeout=15,
        )
    except Exception as exc:  # network, rate limit, parsing, missing package: all non-fatal
        log.warning("Price download failed: %r", exc)
        batch_error = f"Price download failed ({type(exc).__name__})"

    quotes: dict[str, Quote] = {}
    for stock in stocks:
        try:
            closes = _extract_closes(frame, stock.yahoo, allow_flat=len(stocks) == 1)
            quote = quote_from_closes(stock.symbol, closes)
        except Exception as exc:
            log.warning("Could not read %s: %r", stock.symbol, exc)
            quote = Quote(stock.symbol, error=f"Unreadable data ({type(exc).__name__})")
        if quote.error and batch_error:
            quote = replace(quote, error=batch_error)
        quotes[stock.symbol] = quote
    return quotes

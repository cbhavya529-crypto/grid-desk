"""Everything you might want to change lives here: stocks, news feeds, categories, timings.

Edit the tuples below; no other file needs to change.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True)
class Stock:
    symbol: str                      # NSE symbol, e.g. "TATAPOWER"
    name: str
    segment: str
    keywords: tuple[str, ...] = ()   # extra phrases that identify the company in news

    @property
    def yahoo(self) -> str:
        return f"{self.symbol}.NS"

    @property
    def match_terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(t.lower() for t in (self.symbol, self.name, *self.keywords) if t))


@dataclass(frozen=True)
class Feed:
    name: str
    url: str


WATCHLIST: tuple[Stock, ...] = (
    Stock("TATAPOWER", "Tata Power", "Integrated & thermal", ("tata power", "mundra")),
    Stock("NTPC", "NTPC", "Integrated & thermal"),
    Stock("ADANIPOWER", "Adani Power", "Integrated & thermal"),
    Stock("JSWENERGY", "JSW Energy", "Integrated & thermal"),
    Stock("TORNTPOWER", "Torrent Power", "Integrated & thermal"),
    Stock("CESC", "CESC", "Integrated & thermal"),
    Stock("NLCINDIA", "NLC India", "Integrated & thermal"),
    Stock("NHPC", "NHPC", "Renewables"),
    Stock("SJVN", "SJVN", "Renewables"),
    Stock("NTPCGREEN", "NTPC Green Energy", "Renewables", ("ntpc green", "ntpc rel")),
    Stock("ADANIGREEN", "Adani Green Energy", "Renewables", ("adani green",)),
    Stock("ACMESOLAR", "ACME Solar", "Renewables", ("acme solar",)),
    Stock("POWERGRID", "Power Grid Corp", "Transmission & distribution", ("power grid", "powergrid", "pgcil")),
    Stock("ADANIENSOL", "Adani Energy Solutions", "Transmission & distribution"),
    Stock("PFC", "Power Finance Corp", "Power financiers", ("power finance corporation",)),
    Stock("RECLTD", "REC", "Power financiers", ("rec limited", "recpdcl")),
    Stock("IREDA", "IREDA", "Power financiers"),
    Stock("BHEL", "BHEL", "Equipment & manufacturing"),
    Stock("POWERINDIA", "Hitachi Energy India", "Equipment & manufacturing", ("hitachi energy",)),
    Stock("SUZLON", "Suzlon Energy", "Equipment & manufacturing", ("suzlon",)),
    Stock("INOXWIND", "Inox Wind", "Equipment & manufacturing", ("inox wind",)),
    Stock("WAAREEENER", "Waaree Energies", "Equipment & manufacturing", ("waaree",)),
    Stock("PREMIERENE", "Premier Energies", "Equipment & manufacturing"),
    Stock("IEX", "Indian Energy Exchange", "Exchange"),
)


def google_news(query: str, days: int = 7) -> str:
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(f"{query} when:{days}d")
        + "&hl=en-IN&gl=IN&ceid=IN:en"
    )


FEEDS: tuple[Feed, ...] = (
    Feed("Google News: power sector", google_news("India power sector")),
    Feed("Google News: tenders", google_news("power tender OR SECI OR auction MW India")),
    Feed("Google News: transmission", google_news("transmission project India POWERGRID OR TBCB")),
    Feed("Google News: storage", google_news("battery energy storage India MWh")),
    Feed("Google News: renewables", google_news("solar OR wind project India MW commissioned")),
    Feed("Google News: Tata Power", google_news('"Tata Power"')),
    Feed("Google News: power stocks", google_news("power stocks NSE")),
    Feed("Mercom India", "https://www.mercomindia.com/feed"),
    Feed("Power Peak Digest", "https://powerpeakdigest.com/feed/"),
)

# Checked in order; the first category with a matching keyword wins.
CATEGORIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("tata", "Tata Power", ("tata power", "tata sons", "mundra")),
    ("tender", "Tenders & orders", (
        "tender", "tenders", "bid", "bids", "bidder", "bidders", "auction", "rfs", "l1",
        "order", "orders", "contract", "awarded", "awards", "wins", "bags", "secures", "epc",
    )),
    ("policy", "Policy & regulation", (
        "cerc", "merc", "regulator", "regulatory", "ministry", "mnre", "policy", "draft",
        "rules", "guidelines", "scheme", "yojana", "tariff order", "aptel", "cea", "amendment",
    )),
    ("markets", "Markets & deals", (
        "shares", "share price", "stock", "stocks", "ipo", "bond", "bonds", "qip", "stake",
        "invests", "investment", "acquires", "acquisition", "results", "profit", "dividend", "target price",
    )),
    ("govt", "Government projects", (
        "ntpc", "nhpc", "sjvn", "powergrid", "power grid", "nlc", "dvc", "bhel", "psu",
        "state-run", "government", "cabinet", "discom", "thermal power project",
    )),
    ("private", "Private projects", (
        "commissions", "commissioned", "inaugurates", "plant", "project", "capacity",
        "mw", "gw", "mwh", "gwh", "manufacturing", "facility",
    )),
)
OTHER_CATEGORY = ("other", "Other")

PRICE_TTL_SECONDS = 300        # refresh prices every 5 minutes
NEWS_TTL_SECONDS = 900         # refresh news every 15 minutes
PRICE_PERIOD = "1y"            # enough history for the 52-week high/low
TREND_POINTS = 66              # about three months of trading days in the sparkline
NEWS_MAX_AGE_DAYS = 14
NEWS_MAX_ITEMS = 300
HTTP_TIMEOUT = (5, 15)         # (connect, read) seconds
HTTP_WORKERS = 6
USER_AGENT = "Mozilla/5.0 (compatible; GridDesk/1.0; personal research dashboard)"

# Grid Desk

A live dashboard for Indian power-sector stocks and news (tenders, government and private projects, policy, deals).

- **Stocks:** 24 power names from NSE via Yahoo Finance, about 15 minutes delayed. Price, day change, 52-week high, distance from the high, and a 3-month trend line. Updates every 5 minutes.
- **Official:** notices straight from the CEA "What's New" page and MNRE's current notices, plus Ministry of Power and MNRE press releases from PIB. Sorted into regulations and drafts, tenders, reports, schemes and guidelines, and meetings. Admin notices (vacancies, recruitment results) are hidden. Checked every 3 hours.
- **News:** Google News searches plus Mercom India and Power Peak Digest RSS. Deduplicated, sorted newest first, auto-sorted into categories and tagged with the watchlist companies they mention. Updates every 15 minutes.

## Run it on your computer

Needs Python 3.11 or newer (pandas 3 requires it).

```bash
cd grid-desk
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
python -m pytest          # should say "48 passed"
streamlit run app.py      # opens http://localhost:8501
```

## Put it online (free)

1. Push this folder to a GitHub repository.
2. Go to share.streamlit.io, sign in with GitHub, choose **New app**, pick the repo, main file `app.py`.
3. You get a permanent link you can open from your phone.

## Change what it tracks

Everything lives in `powerdesk/config.py`:

- `WATCHLIST`: add a line like `Stock("KPIL", "Kalpataru Projects", "Transmission & distribution", ("kalpataru",))`. The symbol is the NSE symbol; the keywords are phrases that identify the company in headlines.
- `OFFICIAL_PAGES`: add any government page that lists notices in a table, e.g. `OfficialPage("CERC", "https://...")`. If the page loads but nothing is found, the Official tab says so under "sources didn't load".
- `OFFICIAL_NOISE`: words that hide admin notices.
- `FEEDS`: add any RSS feed, or a Google News search with `google_news("your search terms")`.
- `CATEGORIES`: keywords decide the category; the first match wins, top to bottom.
- Timings (refresh intervals, how many days of news) are at the bottom.

After changing anything, run `python -m pytest` before `streamlit run app.py`.

## How it stays up when things go wrong

- A feed that is down, slow, or returns garbage is skipped and listed under "source(s) didn't load"; the rest still show.
- A stock with no data shows "No data returned" in its Status column; the others still show.
- All network calls have timeouts and retry twice on server errors.
- Headlines are escaped before display, and only http/https links are ever shown, so a malicious feed can't inject links, formatting or scripts.
- If any section still hits something unexpected, it shows a message instead of crashing; details go to the terminal log.

## Files

- `app.py`: the page layout.
- `powerdesk/config.py`: what to track (edit this one).
- `powerdesk/prices.py`: stock data.
- `powerdesk/news.py`: news feeds, categorising, company tagging.
- `powerdesk/official.py`: CEA/MNRE notice pages and PIB releases.
- `powerdesk/display.py`: formatting and escaping.
- `tests/`: 48 tests covering normal data, broken feeds, failed downloads and bad values.

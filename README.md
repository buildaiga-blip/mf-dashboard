# My MF Intelligence — Personal Portfolio Dashboard

A personal-investor version of a "Treasury MF Intelligence" style dashboard: scans the mutual
fund universe (via [api.mfapi.in](https://www.mfapi.in/)), ranks the top Direct-Growth **active**
funds per category, and gives you a simple goal-based allocation guide plus a live portfolio value
tracker — all as a static site you can host free on GitHub Pages.

The dashboard has two ranking tabs:
- **Equity** — includes both Equity categories (Large/Mid/Small/Flexi Cap, ELSS) and Hybrid
  categories (Balanced Advantage, Aggressive Hybrid), since hybrid funds are usually considered
  alongside equity in a growth allocation.
- **Debt** — Short Duration, Corporate Bond, Liquid/Overnight.

Each tab sorts independently (Equity defaults to 1Y, Debt to 3M, matching how each asset class is
normally compared), and **only active funds are shown** — see "Active funds only" below.

## Six tabs

1. **Equity** — 10 Equity categories + 6 Hybrid categories (Large Cap, Flexi Cap, ELSS, Balanced
   Advantage, etc.), each its own card, sorted independently from Debt.
2. **Debt** — all 16 SEBI debt categories (Overnight through Gilt), each its own card.
3. **Allocation Guide** — static goal-based guidance (emergency fund, tax saving, retirement, etc.)
4. **My Portfolio** — your actual holdings, valued live.
5. **Financial Updates** — Regulatory (RBI/SEBI/Government, last 2 days) and News (India, Finance &
   Markets, Geopolitics, Economy) sub-tabs, so it's never blank.
6. **Economic Trends** — 5-year charts for Repo Rate, CPI, WPI, 10Y G-Sec yield, USD/INR.
7. **Research** — curated structural sector themes with example companies, plus a live Sensex/Nifty
   market pulse strip and a related-headline tie-in per theme from the News feed (educational, not advice).

## What's inside

```
mf-dashboard/
├── index.html                 # the dashboard (3 tabs: Rankings, Allocation Guide, My Portfolio)
├── assets/
│   ├── style.css               # dark "ledger" theme
│   ├── app.js                  # rendering + live NAV fetch logic
│   └── research_content.js     # curated Research tab content (themes/companies/keywords)
├── data/
│   ├── category_map.json               # rules used to classify scheme names into categories
│   ├── data.json                        # ranked fund data (SAMPLE until first refresh)
│   ├── regulatory_updates.json          # RBI/SEBI/Government announcements (last 2 days)
│   ├── news.json                        # general news across curated categories
│   ├── macro_trends.json                # CPI/G-Sec/USD-INR/Repo/WPI time series + policy rates + market pulse
│   └── repo_rate_extracted_history.json # persisted state for policy-rate extraction (script-managed)
├── fetch_universe.py             # scans mfapi.in, classifies funds, computes returns, writes data.json
├── fetch_regulatory_updates.py   # RBI/SEBI/PIB RSS -> data/regulatory_updates.json
├── fetch_news.py                 # Google News RSS across categories -> data/news.json
├── fetch_macro_trends.py         # FRED + FBIL + RBI homepage + MOSPI -> data/macro_trends.json
├── requirements.txt
└── .github/workflows/
    ├── refresh-data.yml          # fetch_universe.py, daily
    ├── refresh-regulatory.yml    # fetch_regulatory_updates.py, every 6 hours
    ├── refresh-news.yml          # fetch_news.py, every 4 hours
    └── refresh-macro.yml         # fetch_regulatory_updates.py + fetch_macro_trends.py, daily
```

## How the pieces fit together

- **`fetch_universe.py`** (Python, runs on a schedule via GitHub Actions) does the heavy lifting:
  pulls every scheme from mfapi.in, keeps only Direct-Growth plans, classifies them into 10
  personal-investor categories, pulls full NAV history for each candidate, computes 1M/3M/6M/1Y/3Y/5Y
  returns, ranks the top 10 per category, and writes `data/data.json`.
- **`index.html` + `assets/app.js`** (pure static HTML/JS, no server needed) reads that `data.json`
  to render the rankings instantly, and additionally does a **live** client-side fetch to
  `api.mfapi.in/mf/{code}/latest` for your personal holdings in the "My Portfolio" tab, so your
  portfolio value is always current even between scheduled refreshes.

This split exists because GitHub Pages can only serve static files — it can't run Python. The
scheduled Action is what keeps `data.json` "live" without needing a server you pay for or maintain.

## Setup

1. **Create a new GitHub repo** and push everything in this folder to it:
   ```bash
   cd mf-dashboard
   git init
   git add .
   git commit -m "Initial personal MF dashboard"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git push -u origin main
   ```

2. **Enable GitHub Pages**: repo → Settings → Pages → Source: `Deploy from a branch` → Branch:
   `main` / `root`. Your dashboard will be live at
   `https://<your-username>.github.io/<repo-name>/` within a minute or two.

3. **Run the first data refresh** (don't wait for the daily schedule): repo → Actions →
   "Refresh MF Data" → Run workflow. This replaces the sample `data.json` with real, live-ranked
   funds. After that it refreshes automatically every day at ~6:00 PM IST.

4. **(Optional) Run it locally first** to sanity-check before pushing:
   ```bash
   pip install -r requirements.txt
   python fetch_universe.py
   # then open index.html via a local server, e.g.:
   python -m http.server 8000
   # visit http://localhost:8000
   ```
   (Opening `index.html` directly via `file://` will fail the `fetch('data/data.json')` call in
   most browsers due to CORS — always use a local server or GitHub Pages.)

## Active funds only

A fund is only included if it passes two checks:
1. **Open Ended** — Close Ended and Interval Fund schemes have fixed maturities and aren't
   something you can freely buy into today, so they're excluded even if still technically "live".
2. **Recent NAV** — NAVs publish every business day; if a scheme's most recent NAV is more than
   `ACTIVE_MAX_STALE_DAYS` (15) days old, it's treated as matured/wound-up/delisted and dropped.

This check runs in `fetch_universe.py` (server-side, so inactive funds never even make it into
`data.json`) and again client-side in `assets/app.js` (`isFundActive()`) as a safety net for the
"⟳ Refresh Live Data" button and for old cached data. Both thresholds are one constant at the top
of each file if you want to loosen or tighten it.

## Two ways the data stays "live"

1. **Automatic, zero-device (default)** — the GitHub Action in `.github/workflows/refresh-data.yml`
   runs `fetch_universe.py` daily on GitHub's own servers and commits a fresh `data.json`. Your
   GitHub Pages link always reflects that, with nothing running on your machine and no clicks
   needed. This is what makes the *link itself* always current.
2. **On-demand, instant (the "⟳ Refresh Live Data" button)** — anyone viewing the page can click
   this button in the Fund Rankings tab to pull fresh NAV history straight from `api.mfapi.in`
   *in their own browser* for every fund currently shown, recompute all six return periods, and
   re-render immediately — without waiting for the next scheduled Action run. This runs entirely
   client-side (no server, no device setup); it just takes a few seconds since it's fetching NAV
   history for every listed fund with limited concurrency to stay polite to the free API.

Note the refresh button only re-scores the funds *already present* in `data.json` — it doesn't
re-scan the entire mutual fund universe for new entrants (that full scan is what
`fetch_universe.py` does, and it's what the daily Action keeps current). So new funds appearing in
a category, or funds dropping out of the top 10, still show up via the daily automated refresh.

## Financial Updates tab — Regulatory + News sub-tabs (never blank)

The tab has two sub-tabs so it always has something current to show:

**Regulatory** (`fetch_regulatory_updates.py`) pulls official RSS feeds:
- RBI Press Releases & Notifications (`rbi.org.in/pressreleases_rss.xml`, `notifications_rss.xml`)
- SEBI (`sebi.gov.in/sebirss.xml`)
- PIB / Government of India (`pib.gov.in` — the central press-release aggregator across ministries,
  covering Finance Ministry / economy / budget announcements)

Only items published in the last 2 days are kept (`LOOKBACK_DAYS` at the top of the script). Runs
every 6 hours via `.github/workflows/refresh-regulatory.yml`. This sub-tab can legitimately be
empty on quiet days — regulators don't publish daily — which is exactly why the News sub-tab exists.

**News** (`fetch_news.py`) pulls general news via Google News' RSS search endpoint (free, keyless,
long-stable even without official docs) across four curated categories: **India**, **Finance &
Markets**, **Geopolitics**, **Economy**. This sub-tab has content essentially every run regardless
of the regulatory calendar, which is what keeps the Financial Updates tab from ever going blank.
Runs every 4 hours via `.github/workflows/refresh-news.yml`.

## Economic Trends tab — sources and limits (fully automated, no manual data entry)

**Repo Rate is sourced two ways, primary + historical.** The repo rate isn't a continuously-traded
market number — RBI's MPC sets it at ~6 discrete meetings a year — so neither a market-rate proxy
nor "wait for an announcement to land in a 2-day RSS window" reliably surfaces today's actual value.
Fixed with two sources:
- **Primary (always current):** RBI's own homepage (`rbi.org.in`) publishes a live "Current Rates"
  panel — Policy Repo Rate, SDF, MSF, Bank Rate, Fixed Reverse Repo Rate — reflecting whatever is
  true right now, independent of announcement timing. This is what the "Current Policy Rates" panel
  at the top of the tab is built from, and it's why that panel is never empty.
- **Historical (for the chart):** the script also scans RBI announcements from
  `data/regulatory_updates.json` for anything MPC-related and fetches the **full press release**
  (RSS titles/summaries are almost always too short to contain the actual number), regex-matching
  RBI's own standard phrasing. Both sources merge into `data/repo_rate_extracted_history.json` — a
  state file the script reads/updates/writes itself every run, never hand-edited.

**⚠️ Important — verify the number against your own expectation.** A live fetch of RBI's homepage
while building this showed **Policy Repo Rate: 5.25%** (as at 1:00pm, 21-Aug-2026), not 5.75%. That
may mean the figure in an earlier snapshot you had was stale, or RBI's page had changed between when
that snapshot was taken and now — either way, this script pulls from RBI's own live page every run,
so whatever it shows is what RBI's site says *at the moment the Action runs*. If that ever looks
wrong, check `https://www.rbi.org.in/home.aspx` yourself — the "Current Rates" panel is the ground
truth this script is built to mirror exactly.

**USD/INR bug fix:** an earlier version of this script called Frankfurter's v2 API with v1-style
parameters (`symbols=`, a `..` date-range path, expecting a nested `{"rates":{"date":{...}}}`
response) — but v2 actually uses `/v2/rates` with `quotes=` and returns a **flat array** of
`{"date","base","quote","rate"}` objects. The old code silently matched nothing and returned an
empty series, which is why USD/INR showed "No data" even though CPI and G-Sec (both FRED, unaffected
by this bug) worked fine. Fixed to call the correct v2 shape. Source is FBIL (the entity RBI itself
designated to compute the official USD/INR reference rate), published same Mumbai business day.

**CPI and 10-Year G-Sec yield still come from FRED** (`INDCPIALLMINMEI`, `INDIRLTLT01STM`) — these
genuinely are monthly-published official statistics, so there's a floor on how current they can be
that no source swap fixes (CPI for month X is published by MOSPI in month X+1; that's the nature of
the statistic, not a bug). What's guaranteed is you always get the latest point actually published,
never something further behind than that.

**WPI** comes from MOSPI's own public WPI API (`api.mospi.gov.in`). This needs a **one-time free
account signup** (not a recurring task — the same kind of one-time setup as enabling GitHub Pages):

1. Sign up at the MOSPI API platform: POST to `https://api.mospi.gov.in/api/users/usersignup`
   with a username/password (see `esankhyiki.mospi.gov.in/API/WPI API User Manual.pdf` for the
   exact request body, or use Postman as the manual describes).
2. In your GitHub repo: Settings → Secrets and variables → Actions → New repository secret. Add
   `MOSPI_USERNAME` and `MOSPI_PASSWORD` with those credentials.
3. That's it — every run of `refresh-macro.yml` logs in automatically and pulls fresh WPI data.

If those secrets aren't set, WPI is simply skipped (empty chart with a note) rather than failing —
everything else keeps working. MOSPI's response field names aren't fully documented publicly, so
`fetch_wpi_series()` tries several plausible variants defensively; if WPI comes back empty even
with credentials set, check the Action logs for a note about unmatched fields and adjust the
parsing in that function to match what MOSPI actually returns.

Runs daily via `.github/workflows/refresh-macro.yml` (cheap to run, and lets a same-day repo-rate
announcement show up quickly via the auto-extraction step above).

**How the Repo Rate chart builds a real trend over time:** every daily run adds today's date to
`data/repo_rate_extracted_history.json` with whatever RBI's homepage currently shows (step 3a
above) — so even between MPC meetings, the chart accumulates one genuine flat-line point per day,
which is actually correct behaviour for a policy rate (it's *supposed* to be flat between
decisions — that flatness is real information, not missing data). Every time RBI actually changes
the rate, either the homepage bootstrap or the announcement-extraction step (whichever catches it
first) records the new value from that date forward. Give it a few daily runs after first setup and
the line chart will visibly build out; a single run only gives you one point (today), which is
expected on day one.

## Chart interactivity

Each Economic Trends chart shows the exact "as of" date next to its latest value, supports
scroll-to-zoom and drag-to-pan (via `chartjs-plugin-zoom`, loaded from jsDelivr — needs
`hammerjs` as a dependency, also loaded there), has a "Reset zoom" button per chart, and shows a
richer tooltip on hover (formatted date, value with unit, and — for Repo Rate points that came
from an RBI announcement — the announcement title that produced that point).

## Research tab — what it is, and what's live vs. curated

`assets/research_content.js` holds curated, written commentary on 10 structural India growth themes
(banking, capex/infra, manufacturing, renewables, healthcare, IT, consumer, autos, real estate,
insurance), each with an icon, a thesis, a handful of well-known example companies, and a set of
match `keywords`. **The theme write-ups themselves are not a live feed** — predicting sector
outperformance isn't something a free API does — they're meant to be periodically refreshed by
asking an LLM or doing your own research to update the file, then bumping `LAST_REVIEWED`.

Two things on this tab ARE live, reusing data already fetched elsewhere in the pipeline (no new
script needed):
- **Market Pulse strip** at the top — same-day Sensex and Nifty 50 levels, extracted from the same
  RBI homepage fetch used for Current Policy Rates (`extract_market_pulse()` in
  `fetch_macro_trends.py`), since the page already carries a "Capital Market" section alongside
  "Current Rates".
- **Related headline per sector card** — each theme's `keywords` array is matched client-side
  against whatever's currently in `data/news.json` (the same feed powering the News sub-tab), so
  if there's a live headline mentioning e.g. "banking" or "RBI", it surfaces directly under the
  Banking & Financial Services card with a link. No match just means nothing recent happens to
  mention that theme — the card still shows fine without one.

Still explicitly educational/illustrative, not a ranked buy list or personalized advice — see the
disclaimer in the tab itself.

## Customizing categories

Edit `data/category_map.json` — each category has `include`/`exclude` keyword lists matched
against scheme names (e.g. `"large cap"`, `"flexi cap"`). Add or remove categories, and
`fetch_universe.py` will pick up the change on its next run. `TOP_N_PER_CATEGORY` and the ranking
metric (3M for Debt, 1Y for Equity/Hybrid) are configurable at the top of `fetch_universe.py`.

## Roadmap ideas for the future app

- SIP (systematic investment plan) return calculator per fund
- XIRR calculation for the portfolio tracker (needs purchase dates, not just current units)
- Expense ratio + AUM enrichment (mfapi.in doesn't provide these — would need a second data source)
- Push notifications / email digest on refresh (GitHub Action could call a webhook)
- Multi-user accounts if this grows beyond a personal single-browser tool (would need a real backend)

## Disclaimer

This tool surfaces publicly available NAV data for informational purposes only. It is not
investment advice. Past returns don't guarantee future performance — please consider your own
risk profile, goals, and time horizon, or consult a SEBI-registered investment advisor.

# My MF Intelligence — Personal Portfolio Dashboard

A personal-investor version of a "Treasury MF Intelligence" style dashboard: scans the mutual
fund universe (via [api.mfapi.in](https://www.mfapi.in/)), ranks the top Direct-Growth funds per
category (Equity, Hybrid, Debt), and gives you a simple goal-based allocation guide plus a live
portfolio value tracker — all as a static site you can host free on GitHub Pages.

## What's inside

```
mf-dashboard/
├── index.html                 # the dashboard (3 tabs: Rankings, Allocation Guide, My Portfolio)
├── assets/
│   ├── style.css               # dark "ledger" theme
│   └── app.js                  # rendering + live NAV fetch logic
├── data/
│   ├── category_map.json       # rules used to classify scheme names into categories
│   └── data.json                # the ranked fund data the dashboard reads (SAMPLE until first refresh)
├── fetch_universe.py           # scans mfapi.in, classifies funds, computes returns, writes data.json
├── requirements.txt
└── .github/workflows/refresh-data.yml   # runs fetch_universe.py daily and commits the result
```

## How the two pieces fit together

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

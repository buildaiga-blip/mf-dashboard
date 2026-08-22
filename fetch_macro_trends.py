#!/usr/bin/env python3
"""
fetch_macro_trends.py
-----------------------
Builds 5-year time series for key Indian macro indicators for the "Economic
Trends" dashboard tab. Everything here is fetched automatically — there is no
manually-edited data file anywhere in this pipeline. Sources:

1. CPI, 10-Year G-Sec yield, USD/INR, and a Repo Rate baseline come from FRED's
   free, keyless CSV endpoint:
       https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
   Series used:
     - INDCPIALLMINMEI : India CPI, All Items (index, monthly)
     - INDIRLTLT01STM  : India 10-Year Government Bond Yield (%, monthly)
     - DEXINUS         : India Rupees per US Dollar (daily; FRED's own H.10
       release typically lags a few business days behind today, which is a
       Fed publication-schedule fact, not a bug here — this refreshes daily
       so it stays as current as FRED itself is)
     - INDIR3TIB01STM  : OECD "3-Month Interbank Rate: Total for India" (%,
       monthly) — used as the repo-rate proxy backbone. An earlier version of
       this script used IRSTCB01INQ156N ("Central Bank Rates"), but that
       series publishes on a multi-quarter lag and had gone stale; the
       3-month interbank rate tracks the repo corridor closely and updates
       far more recently. It still isn't RBI's own repo-rate series (no free
       API publishes that directly), which is why step 3 below layers real
       RBI announcement values on top wherever one can be caught automatically.
   NOTE: FRED series IDs occasionally get renamed/retired. If a fetch fails,
   check https://fred.stlouisfed.org/tags/series?t=india for the current ID.

2. WPI comes from MOSPI's own WPI API (api.mospi.gov.in) — a free service
   that requires a one-time account signup (not a recurring manual task,
   just initial setup, the same as e.g. enabling GitHub Pages once). See
   "One-time WPI setup" in the README for how to create the account and
   store MOSPI_USERNAME / MOSPI_PASSWORD as GitHub Actions secrets. Without
   those secrets set, this script simply skips WPI (leaves it empty) rather
   than failing — everything else still runs.

3. Repo Rate is refined by scanning data/regulatory_updates.json (produced
   by fetch_regulatory_updates.py, which should run before this script) for
   RBI announcements whose title OR summary mentions "repo rate" followed by
   a percent figure, and merging any it finds into
   data/repo_rate_extracted_history.json — a small state file this script
   reads, updates, and writes back itself every run (not something you edit
   by hand). Persisting it this way means a value extracted today doesn't
   get lost once it falls outside the regulatory-updates 2-day lookback
   window on a later run — the chart keeps accumulating real RBI-announced
   values going forward, permanently, with zero manual editing. This is
   regex-based best-effort extraction, not a guarantee every rate change
   gets caught, but it's the closest to "real" the repo-rate chart gets
   between what FRED publishes.

Run locally:
    pip install -r requirements.txt
    python fetch_macro_trends.py
"""

import csv
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).parent
OUTPUT_PATH = HERE / "data" / "macro_trends.json"
REGULATORY_UPDATES_PATH = HERE / "data" / "regulatory_updates.json"
REPO_RATE_HISTORY_PATH = HERE / "data" / "repo_rate_extracted_history.json"

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
REQUEST_TIMEOUT = 20
YEARS_BACK = 5

FRED_SERIES = {
    "repo_rate": {
        "fred_id": "INDIR3TIB01STM",
        "label": "RBI Repo Rate (3M Interbank proxy via FRED + RBI announcements)",
        "unit": "%",
    },
    "cpi_index": {"fred_id": "INDCPIALLMINMEI", "label": "CPI (All Items, Index)", "unit": "Index"},
    "gsec_10y": {"fred_id": "INDIRLTLT01STM", "label": "10-Year G-Sec Yield", "unit": "%"},
    "usd_inr": {"fred_id": "DEXINUS", "label": "USD/INR Exchange Rate", "unit": "₹ per $"},
}

MOSPI_BASE = "https://api.mospi.gov.in"
MOSPI_USERNAME = os.environ.get("MOSPI_USERNAME")
MOSPI_PASSWORD = os.environ.get("MOSPI_PASSWORD")

REPO_RATE_PATTERN = re.compile(r"repo rate[^0-9]{0,40}(\d{1,2}\.\d{1,2})\s*(?:per\s*cent|%)", re.IGNORECASE)


def fetch_fred_series(fred_id):
    url = FRED_CSV_URL.format(series_id=fred_id)
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    next(reader)  # header row: ["DATE", fred_id]
    cutoff = datetime.now().replace(year=datetime.now().year - YEARS_BACK)
    points = []
    for row in reader:
        if len(row) < 2 or row[1] in (".", ""):
            continue
        try:
            d = datetime.strptime(row[0], "%Y-%m-%d")
            v = float(row[1])
        except ValueError:
            continue
        if d >= cutoff:
            points.append({"date": d.strftime("%Y-%m-%d"), "value": v})
    return points


def load_repo_rate_history():
    """Persisted store of every repo-rate value ever auto-extracted from an RBI
    announcement, keyed by date. This is read-modify-written by the script
    itself on every run — not a manually-edited file — so points don't get
    lost once they age out of the 2-day regulatory-updates lookback window."""
    if not REPO_RATE_HISTORY_PATH.exists():
        return {}
    try:
        with open(REPO_RATE_HISTORY_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_repo_rate_history(history):
    REPO_RATE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPO_RATE_HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2, sort_keys=True)


def extract_repo_rate_from_announcements():
    """Best-effort: scan already-fetched RBI announcements (title AND summary,
    since many RSS titles don't include the actual rate figure) for an
    explicit 'repo rate ... X.XX per cent/%' mention, merge any new finds into
    the persisted history, and return the full accumulated history as points.
    Returns whatever's already persisted (possibly empty) if the regulatory
    updates file doesn't exist yet or nothing new matches."""
    history = load_repo_rate_history()  # {date: {"value": ..., "note": ...}}

    if REGULATORY_UPDATES_PATH.exists():
        try:
            with open(REGULATORY_UPDATES_PATH) as f:
                reg_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            reg_data = {}

        for item in reg_data.get("items", []):
            if item.get("source") != "RBI":
                continue
            haystack = f"{item.get('title', '')} {item.get('summary', '')}"
            match = REPO_RATE_PATTERN.search(haystack)
            if not match:
                continue
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            date = (item.get("published_iso") or "")[:10]
            if not date:
                continue
            history[date] = {
                "value": value,
                "note": f'Auto-extracted from RBI announcement: "{item["title"]}"',
            }

    save_repo_rate_history(history)
    return [{"date": d, "value": v["value"], "note": v["note"]} for d, v in sorted(history.items())]


def get_mospi_token():
    if not MOSPI_USERNAME or not MOSPI_PASSWORD:
        print("MOSPI_USERNAME/MOSPI_PASSWORD not set — skipping WPI (see README for one-time setup).")
        return None
    try:
        resp = requests.post(
            f"{MOSPI_BASE}/api/users/login",
            json={"username": MOSPI_USERNAME, "password": MOSPI_PASSWORD},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("token")
    except requests.RequestException as e:
        print(f"MOSPI login failed: {e}")
        return None


def fetch_wpi_series(token):
    if not token:
        return []
    current_year = datetime.now().year
    years = ",".join(str(y) for y in range(current_year - YEARS_BACK, current_year + 1))
    try:
        resp = requests.get(
            f"{MOSPI_BASE}/api/wpi/getWpiRecords",
            headers={"Authorization": token},
            params={"Year": years, "Format": "JSON"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"WPI fetch failed: {e}")
        return []

    records = payload if isinstance(payload, list) else payload.get("data", payload.get("records", []))
    points = []
    for rec in records or []:
        # Field names aren't fully documented publicly — try the plausible variants defensively.
        group = str(rec.get("Major_Group") or rec.get("major_group") or rec.get("MajorGroup") or "").lower()
        if group and "all commodities" not in group:
            continue
        year = rec.get("Year") or rec.get("year")
        month = rec.get("Month") or rec.get("month_code") or rec.get("Month_Code") or rec.get("month")
        value = rec.get("Index") or rec.get("index_value") or rec.get("WPI") or rec.get("wpi")
        try:
            year, month, value = int(year), int(month), float(value)
        except (TypeError, ValueError):
            continue
        points.append({"date": f"{year:04d}-{month:02d}-01", "value": value})

    points.sort(key=lambda p: p["date"])
    if records and not points:
        print("WPI response received but no records matched the expected fields — "
              "check the raw response shape and adjust fetch_wpi_series() field names.")
    return points


def main():
    indicators = {}

    for key, meta in FRED_SERIES.items():
        print(f"Fetching {meta['label']} (FRED: {meta['fred_id']}) ...")
        try:
            points = fetch_fred_series(meta["fred_id"])
            print(f"  -> {len(points)} point(s)")
        except requests.RequestException as e:
            print(f"  ! Failed: {e}")
            points = []
        indicators[key] = {"label": meta["label"], "unit": meta["unit"], "source": "FRED", "points": points}

    print("Merging repo rate values auto-extracted from RBI announcements (persisted across runs) ...")
    extracted = extract_repo_rate_from_announcements()
    print(f"  -> {len(extracted)} point(s) in accumulated history")
    if extracted:
        combined = {p["date"]: p for p in indicators["repo_rate"]["points"]}
        for p in extracted:
            combined[p["date"]] = p  # extracted/precise values win over the FRED proxy on the same date
        indicators["repo_rate"]["points"] = sorted(combined.values(), key=lambda p: p["date"])

    print("Fetching WPI from MOSPI API ...")
    token = get_mospi_token()
    wpi_points = fetch_wpi_series(token)
    print(f"  -> {len(wpi_points)} point(s)")
    indicators["wpi_yoy"] = {
        "label": "WPI (All Commodities Index)",
        "unit": "Index",
        "source": "MOSPI API (api.mospi.gov.in)" if token else "MOSPI API (not configured — see README)",
        "points": wpi_points,
    }

    for key, series in indicators.items():
        series["as_of"] = series["points"][-1]["date"] if series["points"] else None

    output = {
        "updated": datetime.now().strftime("%d-%b-%Y %H:%M"),
        "indicators": indicators,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

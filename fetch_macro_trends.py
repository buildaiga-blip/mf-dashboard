#!/usr/bin/env python3
"""
fetch_macro_trends.py
-----------------------
Builds 5-year time series for key Indian macro indicators for the "Economic
Trends" dashboard tab. Everything here is fetched automatically — there is no
manually-edited data file anywhere in this pipeline. Sources:

1. CPI, 10-Year G-Sec yield, USD/INR, and a Repo Rate proxy come from FRED's
   free, keyless CSV endpoint:
       https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
   Series used:
     - INDCPIALLMINMEI : India CPI, All Items (index, monthly)
     - INDIRLTLT01STM  : India 10-Year Government Bond Yield (%, monthly)
     - DEXINUS         : India Rupees per US Dollar (daily)
     - IRSTCB01INQ156N : OECD "Central Bank Rates: Total for India" (%,
       quarterly) — a close proxy for the repo rate, used as the long-run
       backbone of that chart. It isn't RBI's own repo-rate series (no free
       API publishes that directly), which is why step 3 below layers real
       RBI announcement values on top wherever we can catch one automatically.
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
   RBI announcements whose title mentions "repo rate" followed by a percent
   figure, and appending any it finds as extra, more precise/current points
   on top of the FRED proxy series. This is regex-based best-effort
   extraction, not a guarantee every rate change gets caught — but it means
   the chart can pick up a same-day change automatically with zero manual
   editing, which was the whole point.

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

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
REQUEST_TIMEOUT = 20
YEARS_BACK = 5

FRED_SERIES = {
    "repo_rate": {
        "fred_id": "IRSTCB01INQ156N",
        "label": "RBI Repo Rate (OECD/FRED proxy + RBI announcements)",
        "unit": "%",
    },
    "cpi_index": {"fred_id": "INDCPIALLMINMEI", "label": "CPI (All Items, Index)", "unit": "Index"},
    "gsec_10y": {"fred_id": "INDIRLTLT01STM", "label": "10-Year G-Sec Yield", "unit": "%"},
    "usd_inr": {"fred_id": "DEXINUS", "label": "USD/INR Exchange Rate", "unit": "₹ per $"},
}

MOSPI_BASE = "https://api.mospi.gov.in"
MOSPI_USERNAME = os.environ.get("MOSPI_USERNAME")
MOSPI_PASSWORD = os.environ.get("MOSPI_PASSWORD")

REPO_RATE_PATTERN = re.compile(r"repo rate[^0-9]{0,30}(\d{1,2}\.\d{1,2})\s*(?:per\s*cent|%)", re.IGNORECASE)


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


def extract_repo_rate_from_announcements():
    """Best-effort: scan already-fetched RBI announcements for an explicit
    'repo rate ... X.XX per cent/%' mention and turn each into a data point.
    Returns [] gracefully if the file doesn't exist yet or nothing matches."""
    if not REGULATORY_UPDATES_PATH.exists():
        return []
    try:
        with open(REGULATORY_UPDATES_PATH) as f:
            reg_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    points = []
    for item in reg_data.get("items", []):
        if item.get("source") != "RBI":
            continue
        match = REPO_RATE_PATTERN.search(item.get("title", ""))
        if not match:
            continue
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        date = (item.get("published_iso") or "")[:10]
        if not date:
            continue
        points.append(
            {
                "date": date,
                "value": value,
                "note": f'Auto-extracted from RBI announcement: "{item["title"]}"',
            }
        )
    return points


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

    print("Extracting repo rate values from RBI announcements ...")
    extracted = extract_repo_rate_from_announcements()
    print(f"  -> {len(extracted)} point(s) auto-extracted")
    if extracted:
        combined = indicators["repo_rate"]["points"] + extracted
        combined.sort(key=lambda p: p["date"])
        indicators["repo_rate"]["points"] = combined

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

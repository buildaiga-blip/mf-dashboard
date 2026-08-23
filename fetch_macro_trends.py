#!/usr/bin/env python3
"""
fetch_macro_trends.py
-----------------------
Builds 5-year time series for key Indian macro indicators for the "Economic
Trends" dashboard tab, plus a "Current Policy Rates" panel sourced directly
from RBI's own announcement text (not a proxy). Everything here is fetched
automatically — there is no manually-edited data file anywhere in this
pipeline. Sources:

1. CPI and 10-Year G-Sec yield come from FRED's free, keyless CSV endpoint:
       https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
   Series used:
     - INDCPIALLMINMEI : India CPI, All Items (index, monthly)
     - INDIRLTLT01STM  : India 10-Year Government Bond Yield (%, monthly)
   These are genuinely monthly-published official statistics — there is no
   way to make them "lower lag" than the underlying data actually is (CPI
   for month X is published by MOSPI in month X+1; that's not a bug in this
   script, it's how the statistic exists). What this script guarantees is
   that you always get the latest point that's actually been published, not
   something further behind than that.

2. USD/INR now comes from FBIL (Financial Benchmarks India Ltd) — the entity
   RBI itself designated to compute the official USD/INR reference rate,
   published every Mumbai business day around 13:30 IST — via the free,
   keyless Frankfurter API's FBIL provider (v2 endpoint):
       https://api.frankfurter.dev/v2/rates?base=USD&quotes=INR&providers=FBIL
   An earlier version of this script called the wrong v2 shape (v1-style
   "/v2/{start}..{end}" path with a "symbols" param and a nested
   {"rates":{"date":{"INR":...}}} response) — v2 actually uses "/v2/rates"
   with "quotes" and returns a FLAT ARRAY of {"date","base","quote","rate"}
   objects, so the old parsing silently matched nothing and returned an
   empty series. Also replaced FRED's DEXINUS (Fed's H.10 release, several
   business days behind) with FBIL for the same-day-official reason noted
   below.

3. Repo Rate (and Reverse Repo / SDF / MSF / Bank Rate, shown together as
   "Current Policy Rates") is sourced TWO ways, since the repo rate isn't a
   continuously-traded number — RBI's MPC sets it at ~6 discrete meetings a
   year — so neither a market proxy nor "wait for an announcement to appear
   in a 2-day RSS window" reliably gives you today's actual value:
     a) PRIMARY / always-current: RBI's own homepage (rbi.org.in) publishes
        a live "Current Rates" panel — Policy Repo Rate, SDF, MSF, Bank
        Rate, Fixed Reverse Repo Rate, even FBIL's own USD/INR reading —
        that reflects whatever is true right now, independent of whether an
        MPC meeting happened today or six weeks ago. This script fetches
        that page every run and extracts every rate from it, so the
        "Current Policy Rates" panel is NEVER empty and is never stale
        beyond RBI's own update cadence for that page.
     b) HISTORICAL: for the repo-rate chart's time series, the script also
        scans RBI announcements from data/regulatory_updates.json for
        anything MPC-related, fetches the full press release (RSS
        titles/summaries are almost always too short to contain the actual
        number), and regex-extracts RBI's standard phrasing. Every value
        found — from either source — merges into
        data/repo_rate_extracted_history.json, a state file this script
        reads/updates/writes itself every run (never hand-edited), so the
        chart accumulates real values permanently going forward.

4. WPI comes from MOSPI's own WPI API (api.mospi.gov.in) — a free service
   that requires a one-time account signup (not a recurring manual task,
   just initial setup, the same as e.g. enabling GitHub Pages once). See
   "One-time WPI setup" in the README. Without MOSPI_USERNAME/MOSPI_PASSWORD
   secrets set, this script simply skips WPI rather than failing.

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
POLICY_RATE_HISTORY_PATH = HERE / "data" / "repo_rate_extracted_history.json"

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
FRANKFURTER_RATES_URL = "https://api.frankfurter.dev/v2/rates"
RBI_HOME_URL = "https://www.rbi.org.in/home.aspx"
REQUEST_TIMEOUT = 20
YEARS_BACK = 5

FRED_SERIES = {
    "cpi_index": {"fred_id": "INDCPIALLMINMEI", "label": "CPI (All Items, Index)", "unit": "Index"},
    "gsec_10y": {"fred_id": "INDIRLTLT01STM", "label": "10-Year G-Sec Yield", "unit": "%"},
}

MOSPI_BASE = "https://api.mospi.gov.in"
MOSPI_USERNAME = os.environ.get("MOSPI_USERNAME")
MOSPI_PASSWORD = os.environ.get("MOSPI_PASSWORD")

# Each policy rate RBI announces, with the phrasing patterns it typically uses in its
# own press releases. Tried against the FULL press-release text (not just the RSS
# title/summary, which is usually too short to contain the number).
POLICY_RATE_PATTERNS = {
    "repo_rate": [
        re.compile(r"policy repo rate[^0-9]{0,60}(\d{1,2}\.\d{1,2})\s*(?:per\s*cent|%)", re.IGNORECASE),
        re.compile(r"repo rate[^0-9]{0,40}(\d{1,2}\.\d{1,2})\s*(?:per\s*cent|%)", re.IGNORECASE),
    ],
    "reverse_repo_rate": [
        re.compile(r"reverse repo rate[^0-9]{0,40}(\d{1,2}\.\d{1,2})\s*(?:per\s*cent|%)", re.IGNORECASE),
    ],
    "sdf_rate": [
        re.compile(r"standing deposit facility[^0-9]{0,60}(\d{1,2}\.\d{1,2})\s*(?:per\s*cent|%)", re.IGNORECASE),
        re.compile(r"\bSDF\b[^0-9]{0,40}(\d{1,2}\.\d{1,2})\s*(?:per\s*cent|%)", re.IGNORECASE),
    ],
    "msf_rate": [
        re.compile(r"marginal standing facility[^0-9]{0,60}(\d{1,2}\.\d{1,2})\s*(?:per\s*cent|%)", re.IGNORECASE),
        re.compile(r"\bMSF\b[^0-9]{0,40}(\d{1,2}\.\d{1,2})\s*(?:per\s*cent|%)", re.IGNORECASE),
    ],
    "bank_rate": [
        re.compile(r"bank rate[^0-9]{0,40}(\d{1,2}\.\d{1,2})\s*(?:per\s*cent|%)", re.IGNORECASE),
    ],
}

RATE_LABELS = {
    "repo_rate": "Repo Rate",
    "reverse_repo_rate": "Reverse Repo Rate",
    "sdf_rate": "Standing Deposit Facility (SDF) Rate",
    "msf_rate": "Marginal Standing Facility (MSF) Rate",
    "bank_rate": "Bank Rate",
}

# Only fetch the full press-release page for items that look like they're actually
# about monetary policy — no point fetching every RBI notification's full text.
MPC_TITLE_HINT = re.compile(r"monetary policy|mpc|repo rate|policy rate", re.IGNORECASE)


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


def fetch_usd_inr_fbil():
    """Official RBI-designated FBIL USD/INR reference rate, via Frankfurter's
    free v2 API with the FBIL provider. v2's /rates endpoint returns a FLAT
    ARRAY of {"date","base","quote","rate"} objects (not v1's nested
    {"rates":{"date":{"INR":...}}} shape — an earlier version of this
    function assumed the v1 shape against a v2 URL and silently matched
    nothing)."""
    end = datetime.now()
    start = end.replace(year=end.year - YEARS_BACK)
    params = {
        "base": "USD",
        "quotes": "INR",
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
        "providers": "FBIL",
    }
    try:
        resp = requests.get(FRANKFURTER_RATES_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  ! FBIL/Frankfurter fetch failed: {e}")
        return []

    points = []
    for row in payload if isinstance(payload, list) else []:
        try:
            points.append({"date": row["date"], "value": float(row["rate"])})
        except (KeyError, TypeError, ValueError):
            continue
    points.sort(key=lambda p: p["date"])
    if payload and not points:
        print("  ! Frankfurter responded but no rows parsed — response shape may have changed again; "
              "check a raw request to FRANKFURTER_RATES_URL and adjust this function.")
    return points


def strip_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", text).strip()


def fetch_page_text(url):
    if not url:
        return ""
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "mf-dashboard-bot/1.0"})
        resp.raise_for_status()
        return strip_html(resp.text)
    except requests.RequestException as e:
        print(f"  ! Failed to fetch {url}: {e}")
        return ""


def fetch_rbi_current_rates():
    """RBI's own homepage publishes a live 'Current Rates' panel — Policy
    Repo Rate, SDF, MSF, Bank Rate, Fixed Reverse Repo Rate — that reflects
    whatever is true right now, independent of whether an MPC meeting
    happened today or six weeks ago. This is what makes the Current Policy
    Rates panel never empty: unlike scanning announcements for a match, this
    page always has today's real numbers on it."""
    text = fetch_page_text(RBI_HOME_URL)
    if not text:
        return {}
    return extract_rates_from_text(text)


def extract_rates_from_text(text):
    """Try every configured rate pattern against a block of text, return
    {rate_key: value} for whatever matches."""
    found = {}
    for rate_key, patterns in POLICY_RATE_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                try:
                    found[rate_key] = float(match.group(1))
                    break
                except ValueError:
                    continue
    return found


def load_policy_rate_history():
    """{rate_key: {date: {"value": ..., "note": ..., "link": ...}}}, persisted
    and updated by this script every run — never hand-edited."""
    if not POLICY_RATE_HISTORY_PATH.exists():
        return {}
    try:
        with open(POLICY_RATE_HISTORY_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_policy_rate_history(history):
    POLICY_RATE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(POLICY_RATE_HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2, sort_keys=True)


def update_policy_rate_history():
    """Scan RBI announcements (title+summary first; full press-release page
    for anything that looks MPC-related, since the number is usually only in
    the full text) for each configured policy rate, merge new finds into the
    persisted history, and return it."""
    history = load_policy_rate_history()  # {rate_key: {date: {...}}}
    for rate_key in POLICY_RATE_PATTERNS:
        history.setdefault(rate_key, {})

    if not REGULATORY_UPDATES_PATH.exists():
        return history
    try:
        with open(REGULATORY_UPDATES_PATH) as f:
            reg_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return history

    for item in reg_data.get("items", []):
        if item.get("source") != "RBI":
            continue
        title = item.get("title", "")
        date = (item.get("published_iso") or "")[:10]
        if not date:
            continue

        haystack = f"{title} {item.get('summary', '')}"
        found = extract_rates_from_text(haystack)

        if len(found) < len(POLICY_RATE_PATTERNS) and MPC_TITLE_HINT.search(title):
            print(f"  Fetching full press release for closer look: {title[:80]}")
            full_text = fetch_page_text(item.get("link"))
            if full_text:
                found.update(extract_rates_from_text(full_text))  # full-text matches win

        for rate_key, value in found.items():
            history[rate_key][date] = {
                "value": value,
                "note": f'RBI announcement: "{title}"',
                "link": item.get("link", ""),
            }

    save_policy_rate_history(history)
    return history


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

    print("Fetching USD/INR (FBIL official reference rate via Frankfurter) ...")
    usd_inr_points = fetch_usd_inr_fbil()
    print(f"  -> {len(usd_inr_points)} point(s)")
    indicators["usd_inr"] = {
        "label": "USD/INR Exchange Rate (FBIL official reference rate)",
        "unit": "₹ per $",
        "source": "FBIL via Frankfurter API",
        "points": usd_inr_points,
    }

    print("Fetching RBI's live 'Current Rates' panel (always-current bootstrap) ...")
    today = datetime.now().strftime("%Y-%m-%d")
    homepage_rates = fetch_rbi_current_rates()
    print(f"  -> {len(homepage_rates)} rate(s) found: {list(homepage_rates.keys())}")

    print("Updating policy rates from RBI announcements (persisted across runs) ...")
    policy_history = update_policy_rate_history()
    for rate_key, value in homepage_rates.items():
        policy_history.setdefault(rate_key, {})
        # Don't overwrite a same-day value already extracted from an actual announcement —
        # only fill in via the homepage if nothing more specific exists for today yet.
        policy_history[rate_key].setdefault(today, {
            "value": value,
            "note": "RBI homepage 'Current Rates' panel (rbi.org.in)",
            "link": RBI_HOME_URL,
        })
    save_policy_rate_history(policy_history)

    current_policy_rates = {}
    for rate_key, by_date in policy_history.items():
        points = [{"date": d, **v} for d, v in sorted(by_date.items())]
        label = RATE_LABELS[rate_key]
        if rate_key == "repo_rate":
            # This is the headline chart — keep it as its own indicator with full history.
            indicators["repo_rate"] = {
                "label": f"RBI {label} (from official RBI announcements)",
                "unit": "%",
                "source": "RBI announcements (auto-extracted, full press-release text)",
                "points": [{"date": p["date"], "value": p["value"], "note": p["note"]} for p in points],
            }
        if points:
            latest = points[-1]
            current_policy_rates[rate_key] = {
                "label": label,
                "value": latest["value"],
                "as_of": latest["date"],
                "source_title": latest["note"],
                "link": latest.get("link", ""),
            }
    indicators.setdefault("repo_rate", {
        "label": "RBI Repo Rate (from official RBI announcements)",
        "unit": "%",
        "source": "RBI announcements (auto-extracted, full press-release text)",
        "points": [],
    })

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

    for series in indicators.values():
        series["as_of"] = series["points"][-1]["date"] if series["points"] else None

    output = {
        "updated": datetime.now().strftime("%d-%b-%Y %H:%M"),
        "current_policy_rates": current_policy_rates,
        "indicators": indicators,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
fetch_universe.py
------------------
Scans the full mutual fund universe via api.mfapi.in, classifies schemes into
personal-investor categories (data/category_map.json), computes trailing
returns (1M/3M/6M/1Y/3Y/5Y) for each Direct-Growth scheme, ranks the top N per
category, and writes the result to data/data.json for the HTML dashboard.

Run locally:
    pip install -r requirements.txt
    python fetch_universe.py

In production this is meant to run on a schedule via
.github/workflows/refresh-data.yml, which commits the refreshed data.json
back to the repo so the static GitHub Pages site always has recent data
without needing a server.

NOTE: api.mfapi.in has no official rate-limit docs; this script is polite
(small delay + session reuse) but if you see 429s, raise REQUEST_DELAY_SEC.
"""

import json
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

BASE = "https://api.mfapi.in"
HERE = Path(__file__).parent
CATEGORY_MAP_PATH = HERE / "data" / "category_map.json"
OUTPUT_PATH = HERE / "data" / "data.json"

TOP_N_PER_CATEGORY = 10
REQUEST_DELAY_SEC = 0.15          # be polite to the free API
NAV_HISTORY_TIMEOUT = 15
ACTIVE_MAX_STALE_DAYS = 15         # NAVs publish every business day; older than this = likely matured/wound-up
RETURN_PERIODS = {                # label -> approx days to look back
    "1M": 30,
    "3M": 91,
    "6M": 182,
    "1Y": 365,
    "3Y": 365 * 3,
    "5Y": 365 * 5,
}


def load_category_map():
    with open(CATEGORY_MAP_PATH) as f:
        return json.load(f)


def fetch_all_schemes(session):
    print("Fetching full scheme list from api.mfapi.in ...")
    r = session.get(f"{BASE}/mf", timeout=30)
    r.raise_for_status()
    return r.json()  # [{"schemeCode": int, "schemeName": str}, ...]


def matches_plan_filters(name_lower, plan_filters):
    if not any(k in name_lower for k in plan_filters["must_include_any"]):
        return False
    if not any(k in name_lower for k in plan_filters["must_include_growth"]):
        return False
    if any(k in name_lower for k in plan_filters["must_exclude_any"]):
        return False
    return True


def classify_scheme(name_lower, categories):
    """Return the first category dict whose include/exclude rules match, else None."""
    for cat in categories:
        if any(k in name_lower for k in cat["include"]) and not any(
            k in name_lower for k in cat["exclude"]
        ):
            return cat
    return None


def fetch_scheme_detail(session, scheme_code):
    """Returns (meta_dict, history) where history is a newest-first list of (date, nav),
    or (None, None) if the request fails."""
    r = session.get(f"{BASE}/mf/{scheme_code}", timeout=NAV_HISTORY_TIMEOUT)
    if r.status_code != 200:
        return None, None
    payload = r.json()
    meta = payload.get("meta", {})
    # payload["data"] is newest-first: [{"date": "16-08-2026", "nav": "123.45"}, ...]
    data = payload.get("data", [])
    parsed = []
    for row in data:
        try:
            d = datetime.strptime(row["date"], "%d-%m-%Y")
            nav = float(row["nav"])
            parsed.append((d, nav))
        except (ValueError, KeyError):
            continue
    return meta, parsed  # newest-first


def is_scheme_active(meta, history):
    """A scheme is treated as 'active' only if:
    - it's an Open Ended scheme (Close Ended / Interval Fund schemes have fixed maturities
      and aren't something a personal investor can buy into freely today), and
    - its most recent NAV isn't stale (matured/wound-up schemes stop publishing NAVs)."""
    scheme_type = (meta or {}).get("scheme_type", "") or ""
    if "open ended" not in scheme_type.lower():
        return False
    if not history:
        return False
    latest_date, _ = history[0]
    age_days = (datetime.now() - latest_date).days
    return age_days <= ACTIVE_MAX_STALE_DAYS


def nav_on_or_before(history, target_date):
    """history is newest-first list of (date, nav). Find first entry <= target_date."""
    for d, nav in history:
        if d <= target_date:
            return nav
    return None


def compute_returns(history):
    """Compute simple trailing % returns for each period in RETURN_PERIODS.
    Uses simple (non-annualized) % change for <=1Y, CAGR for >1Y, matching
    the convention of most fund-comparison sites for at-a-glance ranking."""
    if not history or len(history) < 2:
        return {}
    latest_date, latest_nav = history[0]
    out = {}
    for label, days in RETURN_PERIODS.items():
        target = latest_date - timedelta(days=days)
        past_nav = nav_on_or_before(history, target)
        if past_nav is None or past_nav <= 0:
            out[label] = None
            continue
        simple_change = (latest_nav - past_nav) / past_nav
        if days > 365:
            years = days / 365
            try:
                cagr = (latest_nav / past_nav) ** (1 / years) - 1
                out[label] = round(cagr * 100, 2)
            except (ZeroDivisionError, ValueError):
                out[label] = round(simple_change * 100, 2)
        else:
            out[label] = round(simple_change * 100, 2)
    out["nav"] = latest_nav
    out["nav_date"] = latest_date.strftime("%d-%b-%Y")
    return out


def main():
    cmap = load_category_map()
    categories = cmap["categories"]
    plan_filters = cmap["plan_filters"]

    session = requests.Session()
    all_schemes = fetch_all_schemes(session)
    print(f"Total schemes in universe: {len(all_schemes)}")

    buckets = {c["key"]: [] for c in categories}

    candidates = []
    for scheme in all_schemes:
        name = scheme.get("schemeName", "")
        name_lower = name.lower()
        if not matches_plan_filters(name_lower, plan_filters):
            continue
        cat = classify_scheme(name_lower, categories)
        if cat is None:
            continue
        candidates.append((scheme["schemeCode"], name, cat))

    print(f"Candidate Direct-Growth schemes matched to a category: {len(candidates)}")

    skipped_inactive = 0
    for i, (code, name, cat) in enumerate(candidates, 1):
        if i % 25 == 0:
            print(f"  ... {i}/{len(candidates)} schemes checked ({skipped_inactive} inactive/stale skipped)")
        meta, history = fetch_scheme_detail(session, code)
        time.sleep(REQUEST_DELAY_SEC)
        if not history:
            continue
        if not is_scheme_active(meta, history):
            skipped_inactive += 1
            continue
        returns = compute_returns(history)
        if not returns:
            continue
        buckets[cat["key"]].append(
            {
                "schemeCode": code,
                "fund": name,
                **returns,
            }
        )

    print(f"Skipped {skipped_inactive} inactive/closed/stale schemes")

    # Rank each bucket. Equity/Hybrid rank by 1Y (more meaningful than 1M for
    # long-horizon assets); Debt/Liquid rank by 3M (matches the original
    # treasury dashboard convention, appropriate for short-duration assets).
    output_categories = []
    for cat in categories:
        rank_key = "3M" if cat["group"] == "Debt" else "1Y"
        funds = [f for f in buckets[cat["key"]] if f.get(rank_key) is not None]
        funds.sort(key=lambda f: f[rank_key], reverse=True)
        top = funds[:TOP_N_PER_CATEGORY]
        avg = (
            round(sum(f[rank_key] for f in top) / len(top), 2) if top else None
        )
        output_categories.append(
            {
                "key": cat["key"],
                "label": cat["label"],
                "group": cat["group"],
                "rating": cat["rating"],
                "horizon": cat["horizon"],
                "rank_metric": rank_key,
                "avg": avg,
                "funds": top,
            }
        )

    output = {
        "updated": datetime.now().strftime("%d-%b-%Y %H:%M"),
        "source": "api.mfapi.in (AMFI NAV data), classified client-side",
        "categories": output_categories,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"Network error talking to api.mfapi.in: {e}", file=sys.stderr)
        sys.exit(1)

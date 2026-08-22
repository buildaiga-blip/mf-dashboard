#!/usr/bin/env python3
"""
fetch_regulatory_updates.py
----------------------------
Pulls official RSS feeds from India's financial regulators, keeps only items
published in the last LOOKBACK_DAYS days, tags each with a topic bucket
(interest rates / currency / economy / industries / mutual funds / exchange /
other), and writes data/regulatory_updates.json for the "Financial Updates"
dashboard tab.

Sources (verified public RSS feeds as of Aug 2026):
- RBI Press Releases : https://www.rbi.org.in/pressreleases_rss.xml
- RBI Notifications  : https://www.rbi.org.in/notifications_rss.xml
- SEBI                : https://www.sebi.gov.in/sebirss.xml
- PIB (Government)    : https://www.pib.gov.in/ViewRss.aspx?reg=1&lang=1
    (PIB is the Government of India's central press-release aggregator —
    covers Finance Ministry / economy / budget announcements etc., not just
    RBI/SEBI, which is why it stands in for the general "Government" bucket.)

IRDAI has no public RSS feed that could be verified at the time this script
was written. It's listed as a manual/reference link in the dashboard instead
of an automated feed — see IRDAI_REFERENCE_URL below. If IRDAI publishes one
in future, add it to SOURCES the same way as the others.

Run locally:
    pip install -r requirements.txt
    python fetch_regulatory_updates.py

In production this runs via .github/workflows/refresh-regulatory.yml on a
few-times-a-day schedule (news is time-sensitive, unlike fund NAVs which only
change once a day).
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

HERE = Path(__file__).parent
OUTPUT_PATH = HERE / "data" / "regulatory_updates.json"

LOOKBACK_DAYS = 2
REQUEST_TIMEOUT = 20

SOURCES = [
    {"name": "RBI", "label": "RBI Press Releases", "url": "https://www.rbi.org.in/pressreleases_rss.xml"},
    {"name": "RBI", "label": "RBI Notifications", "url": "https://www.rbi.org.in/notifications_rss.xml"},
    {"name": "SEBI", "label": "SEBI", "url": "https://www.sebi.gov.in/sebirss.xml"},
    {"name": "Government", "label": "PIB (Govt. of India)", "url": "https://www.pib.gov.in/ViewRss.aspx?reg=1&lang=1"},
]

IRDAI_REFERENCE = {
    "source": "IRDAI",
    "label": "IRDAI Press Releases (manual check — no public RSS found)",
    "url": "https://irdai.gov.in/press-releases",
}

# Ordered so the first matching bucket wins when a title mentions multiple things.
TOPIC_RULES = [
    ("Interest Rates", ["repo", "reverse repo", "mpc", "monetary policy", "policy rate", "bank rate", "msf", "sdf"]),
    ("Currency", ["rupee", "forex", "foreign exchange", "fx ", "currency", "dollar"]),
    ("Mutual Funds", ["mutual fund", "amc", "scheme", "nav ", "sip", "amfi"]),
    ("Exchange", ["nse", "bse", "stock exchange", "listing", "trading", "clearing corporation", "depository"]),
    ("Economy", ["gdp", "inflation", "cpi", "wpi", "fiscal", "budget", "growth", "economic survey"]),
    ("Industries", ["sector", "industry", "manufacturing", "infrastructure", "psu", "banking sector"]),
]


def classify_topic(title):
    title_lower = title.lower()
    for topic, keywords in TOPIC_RULES:
        if any(k in title_lower for k in keywords):
            return topic
    return "Other"


def parse_entry_date(entry):
    """feedparser gives *_parsed as a time.struct_time in UTC when available."""
    for key in ("published_parsed", "updated_parsed"):
        val = getattr(entry, key, None)
        if val:
            return datetime(*val[:6], tzinfo=timezone.utc)
    return None


def fetch_source(source):
    try:
        resp = requests.get(source["url"], timeout=REQUEST_TIMEOUT, headers={"User-Agent": "mf-dashboard-bot/1.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ! Failed to fetch {source['label']}: {e}", file=sys.stderr)
        return []

    parsed = feedparser.parse(resp.content)
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    for entry in parsed.entries:
        pub_date = parse_entry_date(entry)
        if pub_date is None or pub_date < cutoff:
            continue
        title = re.sub(r"\s+", " ", getattr(entry, "title", "")).strip()
        if not title:
            continue
        summary_raw = getattr(entry, "summary", "") or ""
        summary = re.sub(r"<[^>]+>", " ", summary_raw)  # strip any HTML tags
        summary = re.sub(r"\s+", " ", summary).strip()[:500]
        items.append(
            {
                "source": source["name"],
                "feed_label": source["label"],
                "title": title,
                "summary": summary,
                "link": getattr(entry, "link", ""),
                "published": pub_date.strftime("%d-%b-%Y %H:%M UTC"),
                "published_iso": pub_date.isoformat(),
                "topic": classify_topic(title),
            }
        )
    return items


def main():
    all_items = []
    for source in SOURCES:
        print(f"Fetching {source['label']} ...")
        items = fetch_source(source)
        print(f"  -> {len(items)} item(s) in the last {LOOKBACK_DAYS} days")
        all_items.extend(items)

    all_items.sort(key=lambda x: x["published_iso"], reverse=True)

    output = {
        "updated": datetime.now().strftime("%d-%b-%Y %H:%M"),
        "lookback_days": LOOKBACK_DAYS,
        "items": all_items,
        "manual_references": [IRDAI_REFERENCE],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(all_items)} item(s) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

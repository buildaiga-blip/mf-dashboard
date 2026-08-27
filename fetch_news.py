#!/usr/bin/env python3
"""
fetch_news.py
--------------
Pulls general news across a few curated categories via Google News' RSS
search endpoint (free, keyless, no official docs but widely used and stable
for years — see https://news.google.com/rss/search?q=<QUERY>&hl=en-IN&gl=IN&
ceid=IN:en). This exists so the Financial Updates tab always has something
current to show, even on days when RBI/SEBI/PIB haven't published anything
in the last 2 days (the regulatory feed's own natural gap).

Categories (chosen to cover what a personal-finance dashboard user would
plausibly care about beyond pure fund data):
  - India             : general India news
  - Finance & Markets : Indian stock market, RBI, mutual funds, banking
  - Geopolitics       : international relations, conflicts, trade, diplomacy
  - Economy           : India/global macroeconomic news, inflation, growth

Run locally:
    pip install -r requirements.txt
    python fetch_news.py
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

HERE = Path(__file__).parent
OUTPUT_PATH = HERE / "data" / "news.json"

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
REQUEST_TIMEOUT = 20
ITEMS_PER_CATEGORY = 12

CATEGORIES = {
    "India": 'India when:2d',
    "Finance & Markets": '(Sensex OR Nifty OR "stock market" OR RBI OR "mutual fund" OR banking) India when:2d',
    "Geopolitics": '(geopolitics OR "international relations" OR diplomacy OR sanctions OR conflict) when:2d',
    "Economy": '(economy OR GDP OR inflation OR "interest rates") (India OR global) when:2d',
}


def fetch_category(category, query):
    params = {"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    try:
        resp = requests.get(
            GOOGLE_NEWS_RSS, params=params, timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "mf-dashboard-bot/1.0"},
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ! Failed to fetch {category}: {e}")
        return []

    parsed = feedparser.parse(resp.content)
    items = []
    for entry in parsed.entries[:ITEMS_PER_CATEGORY]:
        title = re.sub(r"\s+", " ", getattr(entry, "title", "")).strip()
        if not title:
            continue
        # Google News titles are usually "Headline - Source Name"; split that out.
        source = ""
        if " - " in title:
            title, source = title.rsplit(" - ", 1)
        pub_date = None
        if getattr(entry, "published_parsed", None):
            pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        items.append(
            {
                "category": category,
                "title": title.strip(),
                "source": source.strip() or "Google News",
                "link": getattr(entry, "link", ""),
                "published": pub_date.strftime("%d-%b-%Y %H:%M UTC") if pub_date else "",
                "published_iso": pub_date.isoformat() if pub_date else "",
            }
        )
    return items


def main():
    all_items = []
    for category, query in CATEGORIES.items():
        print(f"Fetching news for category: {category} ...")
        items = fetch_category(category, query)
        print(f"  -> {len(items)} item(s)")
        all_items.extend(items)

    all_items.sort(key=lambda x: x["published_iso"], reverse=True)

    output = {
        "updated": datetime.now().strftime("%d-%b-%Y %H:%M"),
        "categories": list(CATEGORIES.keys()),
        "items": all_items,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(all_items)} item(s) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Draw a manual-verification sample (M2): N random scored listings per city -> CSV for the owner.

Usage: python scripts/review_sample.py scored.json out.csv [--per-city 5] [--seed 20261118]
"""
from __future__ import annotations

import argparse
import csv
import json
import random

COLUMNS = ["city", "url", "priceLocal", "areaM2", "rooms", "district", "pricePerM2Eur", "dealScore"]


def draw(scored: list[dict], per_city: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    by_city: dict[str, list[dict]] = {}
    for rec in scored:
        by_city.setdefault(rec["city"], []).append(rec)
    rows = []
    for city in sorted(by_city):
        recs = sorted(by_city[city], key=lambda r: r["listingId"])
        for rec in rng.sample(recs, min(per_city, len(recs))):
            rows.append({
                "city": rec["city"],
                "url": rec["url"],
                "priceLocal": rec["price"]["local"],
                "areaM2": rec["areaM2"],
                "rooms": rec["rooms"],
                "district": rec["district"],
                "pricePerM2Eur": rec["pricePerM2Eur"],
                "dealScore": rec["dealScore"],
            })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scored_json")
    ap.add_argument("out_csv")
    ap.add_argument("--per-city", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20261118)
    args = ap.parse_args()
    scored = json.load(open(args.scored_json))["scoredListings"]
    rows = draw(scored, args.per_city, args.seed)
    with open(args.out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows -> {args.out_csv}")


if __name__ == "__main__":
    main()

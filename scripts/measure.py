#!/usr/bin/env python3
"""Live measurement for the §13 gate: pages, items, blocks, bytes, time, district x rooms coverage.

Usage: python scripts/measure.py [--per-district N] [--gb-price USD] [city ...]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

from src.clean import clean_listings
from src.config import CITIES
from src.http import HttpClient
from src.sources.otodom import OtodomSource, parse_otodom_items
from src.stats import district_group_coverage, gate_coverage

DOMAIN = "www.otodom.pl"


async def measure_city(
    city_key: str,
    http: HttpClient,
    max_listings: int,
    max_per_district: int | None,
) -> dict:
    cfg = CITIES[city_key]
    result = {"city": city_key, "source": cfg.source, "sides": {}}
    all_cleaned = []

    for tx in ("sale", "rent"):
        t0 = time.monotonic()
        ds = http.domain_stats.get(DOMAIN)
        req0, blk0, bytes0 = (ds.requests, ds.blocked, ds.bytes_downloaded) if ds else (0, 0, 0)

        try:
            if cfg.source != "otodom":
                raise RuntimeError(f"Unsupported source: {cfg.source}")
            raw_items, stats = await OtodomSource(http).fetch_listings(
                city_key, tx, max_listings, max_per_district=max_per_district,
            )
            listings, rejected = parse_otodom_items(raw_items, cfg, tx)
            cleaned, clean_rejected = clean_listings(listings)
            all_cleaned.extend(cleaned)

            ds = http.domain_stats[DOMAIN]
            requests = ds.requests - req0
            blocked = ds.blocked - blk0
            result["sides"][tx] = {
                "pages": stats["pages_fetched"],
                "districts": stats.get("districts"),
                "raw_items": stats["raw_items"],
                "parsed": len(listings),
                "cleaned": len(cleaned),
                "rejected_parse": rejected,
                "rejected_clean": clean_rejected,
                "requests": requests,
                "blocked_pct": round(blocked / requests * 100, 1) if requests else 0.0,
                "bytes": ds.bytes_downloaded - bytes0,
                "time_s": round(time.monotonic() - t0, 1),
                "build_id_refreshes": stats.get("build_id_refreshes", 0),
                "fallback_to_html": stats.get("fallback_to_html", False),
            }
        except Exception as e:
            result["sides"][tx] = {"error": str(e), "time_s": round(time.monotonic() - t0, 1)}

    result["gate"] = gate_coverage(all_cleaned).get(cfg.display_name)
    result["coverage"] = district_group_coverage(all_cleaned).get(cfg.display_name)
    return result


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="*", default=list(CITIES))
    ap.add_argument("--max-listings", type=int, default=1500)
    ap.add_argument("--per-district", type=int, default=None)
    ap.add_argument("--gb-price", type=float, default=8.0, help="residential proxy USD/GB")
    args = ap.parse_args()

    http = HttpClient()
    results = []
    for city_key in args.cities:
        if city_key not in CITIES:
            print(f"Unknown city: {city_key}")
            continue
        print(f"Measuring {city_key}...", flush=True)
        results.append(await measure_city(city_key, http, args.max_listings, args.per_district))
    await http.close()

    print("\n" + "=" * 104)
    print(f"{'City':<10} {'Side':<5} {'Pages':>6} {'Raw':>6} {'Parsed':>7} {'Clean':>6} "
          f"{'Block%':>7} {'MB*':>7} {'Time':>7}")
    print("-" * 104)
    for r in results:
        city_bytes = 0
        for tx in ("sale", "rent"):
            s = r["sides"].get(tx, {})
            if "error" in s:
                print(f"{r['city']:<10} {tx:<5} ERROR: {s['error']}")
                continue
            city_bytes += s["bytes"]
            print(f"{r['city']:<10} {tx:<5} {s['pages']:>6} {s['raw_items']:>6} {s['parsed']:>7} "
                  f"{s['cleaned']:>6} {s['blocked_pct']:>6.1f}% {s['bytes'] / 1e6:>7.1f} {s['time_s']:>6.1f}s")
            print(f"{'':>17} parse rejections: {s['rejected_parse']}")
            print(f"{'':>17} clean rejections: {s['rejected_clean']}")
        gate = r["gate"] or {}
        cov = r["coverage"] or {}
        city_time = sum(s.get("time_s", 0) for s in r["sides"].values())
        print(f"{'':>17} city: {city_bytes / 1e6:.1f} MB* -> ${city_bytes / 1e9 * args.gb_price:.2f} "
              f"at ${args.gb_price}/GB, {city_time:.0f}s")
        print(f"{'':>17} gate (binding): {gate.get('districtLevel')}/{gate.get('scoredListings')} scored sales "
              f"at district level = {gate.get('districtLevelPct')}%")
        print(f"{'':>17} groups (info):  {cov.get('fullGroups')}/{cov.get('groups')} district x rooms "
              f"with both thresholds = {cov.get('coveragePct')}%")
    print("=" * 104)
    print("* decompressed response bytes; proxy traffic (compressed) is lower, so cost is an upper bound")

    print("\nJSON output:")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

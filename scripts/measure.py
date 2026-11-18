#!/usr/bin/env python3
"""Live measurement for the §13 gate: pages, items, blocks, bytes, time, district x rooms coverage.

Usage: python scripts/measure.py [--per-district N] [--gb-price USD] [city ...]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from src.clean import clean_listings
from src.config import CITIES
from src.http import HttpClient
from src.output import build_side_summary
from src.sources.otodom import OtodomSource, parse_otodom_items
from src.stats import district_group_coverage, gate_coverage

DOMAIN = "www.otodom.pl"


def investment_summary(raw_items: list[dict]) -> dict | None:
    """What INVESTMENT (developer project) tiles contain; computed before the parser strips them."""
    tiles = [it for it in raw_items if it.get("estate") == "INVESTMENT"]
    if not tiles:
        return None
    units = [t["investmentUnitsNumber"] for t in tiles if isinstance(t.get("investmentUnitsNumber"), int)]
    price_from = [t["priceFromPerSquareMeter"]["value"] for t in tiles
                  if (t.get("priceFromPerSquareMeter") or {}).get("value")]
    years = [t["investmentEstimatedDelivery"]["year"] for t in tiles
             if (t.get("investmentEstimatedDelivery") or {}).get("year")]
    return {
        "tiles": len(tiles),
        "uniqueTiles": len({t.get("id") for t in tiles}),
        "states": dict(Counter(t.get("investmentState") for t in tiles)),
        "unitsTotal": sum(units),
        "unitsMedian": statistics.median(units) if units else None,
        "priceFromPerM2Median": statistics.median(price_from) if price_from else None,
        "deliveryYears": dict(sorted(Counter(years).items())),
        "withTotalPrice": sum(1 for t in tiles if t.get("totalPrice")),
        "withArea": sum(1 for t in tiles if t.get("areaInSquareMeters")),
        "relatedAdsMedian": statistics.median(len(t.get("relatedAds") or []) for t in tiles),
        "tileDevelopmentIdNonZero": sum(1 for t in tiles if (t.get("developmentId") or 0) > 0),
    }


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
            investments = investment_summary(raw_items)
            listings, rejected = parse_otodom_items(raw_items, cfg, tx)
            cleaned, clean_rejected = clean_listings(listings)
            all_cleaned.extend(cleaned)

            ds = http.domain_stats[DOMAIN]
            requests = ds.requests - req0
            blocked = ds.blocked - blk0
            elapsed = time.monotonic() - t0
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
                "time_s": round(elapsed, 1),
                "build_id_refreshes": stats.get("build_id_refreshes", 0),
                "fallback_to_html": stats.get("fallback_to_html", False),
                "district_source": stats.get("district_source"),
                "investments": investments,
                "run_summary": build_side_summary(
                    stats, rejected, clean_rejected, len(cleaned), requests, blocked, elapsed,
                ),
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
    ap.add_argument("--json-out", default=None, help="also write the JSON results to this file")
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
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())

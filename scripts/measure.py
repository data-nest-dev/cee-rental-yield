#!/usr/bin/env python3
"""Live measurement script for weekend 1 gate decision.

Fetches listings from all configured cities, reports:
- Pages fetched, raw items, % blocks, time, bytes downloaded
- % of district×rooms groups with full sample

Usage: python scripts/measure.py [city1 city2 ...]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

from src.clean import clean_listings
from src.config import CITIES
from src.http import HttpClient
from src.sources.otodom import OtodomSource, parse_otodom_items
from src.sources.sreality import SrealitySource, parse_sreality_items


async def measure_city(
    city_key: str,
    http: HttpClient,
    max_listings: int = 1500,
) -> dict:
    cfg = CITIES[city_key]
    result = {"city": city_key, "source": cfg.source, "sides": {}}

    for tx in ("sale", "rent"):
        t0 = time.monotonic()

        try:
            if cfg.source == "otodom":
                source = OtodomSource(http)
                raw_items, stats = await source.fetch_listings(city_key, tx, max_listings)
                listings, rejected = parse_otodom_items(raw_items, cfg, tx)
            else:
                source = SrealitySource(http)
                raw_items, stats = await source.fetch_listings(city_key, tx, max_listings)
                listings, rejected = parse_sreality_items(raw_items, cfg, tx)

            cleaned, clean_rejected = clean_listings(listings)

            elapsed = time.monotonic() - t0
            domain = "www.otodom.pl" if cfg.source == "otodom" else "www.sreality.cz"
            ds = http.domain_stats.get(domain)
            blocked_pct = (ds.blocked / ds.requests * 100) if ds and ds.requests > 0 else 0

            result["sides"][tx] = {
                "pages": stats["pages_fetched"],
                "raw_items": stats["raw_items"],
                "parsed": len(listings),
                "cleaned": len(cleaned),
                "rejected_parse": rejected,
                "rejected_clean": clean_rejected,
                "blocked_pct": round(blocked_pct, 1),
                "bytes": ds.bytes_downloaded if ds else 0,
                "time_s": round(elapsed, 1),
                "build_id_refreshes": stats.get("build_id_refreshes", 0),
                "fallback_to_html": stats.get("fallback_to_html", False),
            }

        except Exception as e:
            elapsed = time.monotonic() - t0
            result["sides"][tx] = {"error": str(e), "time_s": round(elapsed, 1)}

    return result


async def main() -> None:
    cities = sys.argv[1:] if len(sys.argv) > 1 else list(CITIES.keys())

    http = HttpClient()
    results = []

    for city_key in cities:
        if city_key not in CITIES:
            print(f"Unknown city: {city_key}")
            continue
        print(f"Measuring {city_key}...")
        r = await measure_city(city_key, http)
        results.append(r)

    await http.close()

    # Print table
    print("\n" + "=" * 100)
    print(f"{'City':<12} {'Side':<6} {'Pages':>6} {'Raw':>6} {'Parsed':>7} {'Clean':>6} {'Block%':>7} {'KB':>8} {'Time':>6}")
    print("-" * 100)
    for r in results:
        for tx in ("sale", "rent"):
            s = r["sides"].get(tx, {})
            if "error" in s:
                print(f"{r['city']:<12} {tx:<6} ERROR: {s['error']}")
            else:
                print(
                    f"{r['city']:<12} {tx:<6} {s['pages']:>6} {s['raw_items']:>6} "
                    f"{s['parsed']:>7} {s['cleaned']:>6} {s['blocked_pct']:>6.1f}% "
                    f"{s['bytes']//1024:>7}K {s['time_s']:>5.1f}s"
                )
                if s.get("rejected_parse"):
                    print(f"{'':>20} parse rejections: {s['rejected_parse']}")
                if s.get("rejected_clean"):
                    print(f"{'':>20} clean rejections: {s['rejected_clean']}")
    print("=" * 100)

    # JSON output
    print("\nJSON output:")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

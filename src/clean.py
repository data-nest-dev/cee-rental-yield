from __future__ import annotations

import math
from src.models import Listing


def clean_listings(
    listings: list[Listing],
    area_min: float = 15.0,
    area_max: float = 250.0,
    counters: dict[str, int] | None = None,
) -> tuple[list[Listing], dict[str, int]]:
    rejected: dict[str, int] = {}
    counters = counters if counters is not None else {}

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    # Steps 1-2 (PII removal, ad inserts, non-flat, outside city) already done in parser.
    # Steps 3-4 (price/area validation, swapped rent) also done in parser.
    # Here we handle: area bounds, dedup across sources, and outlier removal.

    result: list[Listing] = []
    seen: set[str] = set()
    seen_twins: set[tuple] = set()

    for ls in listings:
        # Dedup by (source, transaction, dedup_key) — parser already deduped within
        # one fetch, but across cities or repeated calls we re-check.
        key = (ls.source, ls.transaction, ls.dedup_key)
        if key in seen:
            reject("duplicate")
            continue
        seen.add(key)

        # Area bounds (§8 step 6)
        if ls.area_m2 < area_min or ls.area_m2 > area_max:
            reject("area_out_of_range")
            continue

        # Same unit posted repeatedly under different slugs (agency reposts). For rent the repeats
        # would count one flat many times in the median, so they are dropped; for sale a developer
        # really does sell several identical flats, so they are only counted.
        twin = _twin_key(ls)
        if twin in seen_twins:
            if ls.transaction == "rent":
                reject("near_duplicate_rent")
                continue
            counters["near_duplicate_sale"] = counters.get("near_duplicate_sale", 0) + 1
        seen_twins.add(twin)

        result.append(ls)

    # Outlier removal (§8 step 7): per city, 1st-99th percentile of price/m²
    result = _remove_outliers(result, rejected)

    return result, rejected


def _twin_key(ls: Listing) -> tuple:
    """Missing fields count as empty values."""
    return (ls.city, ls.transaction, ls.district, ls.rooms, ls.area_m2, ls.price_local, ls.floor, ls.advertiser_type)


def _remove_outliers(
    listings: list[Listing],
    rejected: dict[str, int],
) -> list[Listing]:
    # Group by (city, transaction)
    groups: dict[tuple[str, str], list[Listing]] = {}
    for ls in listings:
        key = (ls.city, ls.transaction)
        groups.setdefault(key, []).append(ls)

    kept: list[Listing] = []
    for group_key, group in groups.items():
        prices_per_m2 = [ls.price_local / ls.area_m2 for ls in group]
        if len(prices_per_m2) < 10:
            kept.extend(group)
            continue

        p1, p99 = _percentile(prices_per_m2, 1), _percentile(prices_per_m2, 99)

        for ls in group:
            ppm2 = ls.price_local / ls.area_m2
            if ppm2 < p1 or ppm2 > p99:
                rejected["outlier"] = rejected.get("outlier", 0) + 1
            else:
                kept.append(ls)

    return kept


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    n = len(s)
    k = (pct / 100) * (n - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[f]
    return s[f] * (c - k) + s[c] * (k - f)

from __future__ import annotations

import math
from dataclasses import replace

from src.models import Listing

# Rooms look wrong when a flat has less than this area per room (e.g. 7 rooms in 27 m2).
MIN_M2_PER_ROOM = 8.0
SUSPECT_ROOMS_FLAG = "suspectRooms"


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

        if ls.rooms and ls.area_m2 / ls.rooms < MIN_M2_PER_ROOM and SUSPECT_ROOMS_FLAG not in ls.flags:
            ls = replace(ls, flags=ls.flags + (SUSPECT_ROOMS_FLAG,))

        # Same rental posted repeatedly under different slugs (agency reposts) would count one flat many
        # times in the median, so repeats are dropped. Identical sale listings are merged below.
        if ls.transaction == "rent":
            twin = _twin_key(ls)
            if twin in seen_twins:
                reject("near_duplicate_rent")
                continue
            seen_twins.add(twin)

        result.append(ls)

    result = _merge_identical_sales(result, counters)

    # Outlier removal (§8 step 7): per city, 1st-99th percentile of price/m²
    result = _remove_outliers(result, rejected)

    return result, rejected


def _id_order(ls: Listing) -> tuple[int, int | str]:
    return (0, int(ls.listing_id)) if ls.listing_id.isdigit() else (1, ls.listing_id)


def _merge_identical_sales(listings: list[Listing], counters: dict[str, int]) -> list[Listing]:
    """One record per group of identical sale listings (same city, district, rooms, area, price).

    A developer lists several identical flats; they would count many times in the medians and be charged
    many times. The representative is the lowest listing ID (stable between runs); the others are listed
    in identical_ids.
    """
    groups: dict[tuple, list[Listing]] = {}
    out: list[Listing | tuple] = []
    for ls in listings:
        if ls.transaction != "sale":
            out.append(ls)
            continue
        key = (ls.city, ls.district, ls.rooms, ls.area_m2, ls.price_local)
        if key not in groups:
            groups[key] = []
            out.append(key)
        groups[key].append(ls)
    merged: list[Listing] = []
    for item in out:
        if isinstance(item, Listing):
            merged.append(item)
            continue
        members = sorted(groups[item], key=_id_order)
        rep, others = members[0], members[1:]
        counters["identical_merged"] = counters.get("identical_merged", 0) + len(others)
        merged.append(replace(
            rep, identical_ids=tuple(o.listing_id for o in others), identical_keys=tuple(o.dedup_key for o in others),
        ) if others else rep)
    return merged


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

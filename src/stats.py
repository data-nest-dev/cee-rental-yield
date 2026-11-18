from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from src.models import Listing


@dataclass
class GroupStats:
    country: str
    city: str
    district: str | None
    rooms_bucket: str
    group_level: str
    confidence: str
    sale_listings: list[Listing]
    rent_listings: list[Listing]
    sale_price_per_m2: list[float]
    rent_per_m2: list[float]


def compute_groups(
    listings: list[Listing],
    min_sale_sample: int = 15,
    min_rent_sample: int = 10,
) -> list[GroupStats]:
    sale = [ls for ls in listings if ls.transaction == "sale"]
    rent = [ls for ls in listings if ls.transaction == "rent"]

    sale_by_group = _group_listings(sale)
    rent_by_group = _group_listings(rent)

    all_keys = set(sale_by_group.keys()) | set(rent_by_group.keys())
    district_keys = [k for k in all_keys if k[1] is not None]

    results: list[GroupStats] = []

    for key in district_keys:
        country, district, city, rooms = key[0], key[1], key[2], key[3]
        s = sale_by_group.get(key, [])
        r = rent_by_group.get(key, [])

        s_ppm2 = [ls.price_local / ls.area_m2 for ls in s]
        r_ppm2 = [ls.price_local / ls.area_m2 for ls in r]

        # Check if district level is sufficient
        if len(s) >= min_sale_sample and len(r) >= min_rent_sample:
            level = "district"
            conf = "high" if len(s) >= 40 else "medium"
        else:
            # Fallback to city + rooms
            city_rooms_key = (country, None, city, rooms)
            s = sale_by_group.get(city_rooms_key, [])
            r = rent_by_group.get(city_rooms_key, [])
            s_ppm2 = [ls.price_local / ls.area_m2 for ls in s]
            r_ppm2 = [ls.price_local / ls.area_m2 for ls in r]

            if len(s) >= min_sale_sample and len(r) >= min_rent_sample:
                level = "city_rooms"
                conf = "medium"
            else:
                # Fallback to city only
                city_key = (country, None, city, None)
                s = sale_by_group.get(city_key, [])
                r = rent_by_group.get(city_key, [])
                s_ppm2 = [ls.price_local / ls.area_m2 for ls in s]
                r_ppm2 = [ls.price_local / ls.area_m2 for ls in r]
                level = "city"
                conf = "low"

        results.append(GroupStats(
            country=country,
            city=city,
            district=district if level == "district" else None,
            rooms_bucket=rooms if rooms else "all",
            group_level=level,
            confidence=conf,
            sale_listings=s,
            rent_listings=r,
            sale_price_per_m2=s_ppm2,
            rent_per_m2=r_ppm2,
        ))

    return results


def _group_listings(
    listings: list[Listing],
) -> dict[tuple, list[Listing]]:
    groups: dict[tuple, list[Listing]] = {}

    for ls in listings:
        rooms_bucket = _rooms_bucket(ls.rooms)

        # District level (only if rooms known)
        if ls.district and rooms_bucket:
            key = (ls.country, ls.district, ls.city, rooms_bucket)
            groups.setdefault(key, []).append(ls)

        # City + rooms level
        if rooms_bucket:
            key = (ls.country, None, ls.city, rooms_bucket)
            groups.setdefault(key, []).append(ls)

        # City level (all rooms)
        key = (ls.country, None, ls.city, None)
        groups.setdefault(key, []).append(ls)

    return groups


def _rooms_bucket(rooms: int | None) -> str | None:
    if rooms is None:
        return None
    if rooms >= 4:
        return "4+"
    return str(rooms)


def district_group_coverage(
    listings: list[Listing],
    min_sale: int = 15,
    min_rent: int = 10,
) -> dict[str, dict]:
    """Per city: share of observed district x roomsBucket groups meeting both sample thresholds."""
    counts: dict[str, dict[tuple[str, str], dict[str, int]]] = {}
    for ls in listings:
        rb = _rooms_bucket(ls.rooms)
        if not ls.district or not rb:
            continue
        g = counts.setdefault(ls.city, {}).setdefault((ls.district, rb), {"sale": 0, "rent": 0})
        g[ls.transaction] += 1

    result: dict[str, dict] = {}
    for city, groups in counts.items():
        full = sum(1 for g in groups.values() if g["sale"] >= min_sale and g["rent"] >= min_rent)
        result[city] = {
            "groups": len(groups),
            "fullGroups": full,
            "coveragePct": round(full / len(groups) * 100, 1),
        }
    return result


def median_val(data: list[float]) -> float:
    if not data:
        return 0.0
    return statistics.median(data)


def quartiles(data: list[float]) -> tuple[float, float, float]:
    if len(data) < 2:
        m = median_val(data)
        return m, m, m
    qs = statistics.quantiles(data, n=4, method="inclusive")
    return qs[0], qs[1], qs[2]


def gross_yield_pct(median_rent_per_m2: float, median_sale_per_m2: float) -> float:
    if median_sale_per_m2 <= 0:
        return 0.0
    return 12 * median_rent_per_m2 / median_sale_per_m2 * 100


def gross_yield_range(
    r25: float, r75: float, p25: float, p75: float,
) -> list[float]:
    low = 12 * r25 / p75 * 100 if p75 > 0 else 0.0
    high = 12 * r75 / p25 * 100 if p25 > 0 else 0.0
    return [low, high]


def deal_score(
    price_per_m2: float,
    sale_prices_per_m2: list[float],
) -> int:
    if len(sale_prices_per_m2) < 2:
        return 50

    ln_prices = [math.log(p) for p in sale_prices_per_m2 if p > 0]
    if not ln_prices:
        return 50

    med_ln = statistics.median(ln_prices)
    deviations = [abs(lp - med_ln) for lp in ln_prices]
    mad = statistics.median(deviations)

    ln_pi = math.log(price_per_m2) if price_per_m2 > 0 else med_ln

    if mad == 0:
        if ln_pi == med_ln:
            return 50
        return 100 if ln_pi < med_ln else 0

    z = (med_ln - ln_pi) / (1.4826 * mad)
    phi = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return round(100 * phi)


def discount_vs_median_pct(
    price_per_m2: float,
    median_price_per_m2: float,
) -> float:
    if median_price_per_m2 <= 0:
        return 0.0
    return (median_price_per_m2 - price_per_m2) / median_price_per_m2 * 100

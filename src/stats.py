from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date

from src.models import Listing


LEVELS = ("district", "city_rooms", "city")


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


@dataclass
class GroupIndex:
    """Listings per (level, key) for each side; key = (country, city, district, roomsBucket)."""
    sale: dict[tuple, list[Listing]]
    rent: dict[tuple, list[Listing]]


@dataclass
class ListingComparables:
    sale_level: str
    sale_listings: list[Listing]
    rent_level: str | None
    rent_listings: list[Listing]
    confidence: str


def group_keys(ls: Listing) -> list[tuple]:
    """(level, key) from finest to coarsest that this listing belongs to."""
    rb = listing_rooms_bucket(ls)
    keys = []
    if ls.district and rb:
        keys.append(("district", (ls.country, ls.city, ls.district, rb)))
    if rb:
        keys.append(("city_rooms", (ls.country, ls.city, None, rb)))
    keys.append(("city", (ls.country, ls.city, None, None)))
    return keys


def index_groups(listings: list[Listing]) -> GroupIndex:
    index = GroupIndex(sale={}, rent={})
    for ls in listings:
        side = index.sale if ls.transaction == "sale" else index.rent
        for level_key in group_keys(ls):
            side.setdefault(level_key, []).append(ls)
    return index


# Full-sample rule (CLAUDE.md section 20.1d, as in the Imovirtual Actor): city-level rows rest on a near-complete
# sample of the city's supply only when the fetched share is high, so they earn `high` just then and only with
# enough listings on both sides. Before: city_rooms was always `medium` and city always `low`.
FULL_SAMPLE_SHARE = 0.8
CITY_ROOMS_HIGH_MIN_SALE = 100
CITY_ROOMS_HIGH_MIN_RENT = 30
CITY_HIGH_MIN_SALE = 200
CITY_HIGH_MIN_RENT = 50


def _confidence(level: str | None, sale_count: int, rent_count: int = 0, sample_share: float | None = None) -> str:
    """district: high from 40 sales, else medium. city_rooms / city: medium / low, unless the sample share is at
    least FULL_SAMPLE_SHARE and both sides reach the count thresholds (then high)."""
    full = sample_share is not None and sample_share >= FULL_SAMPLE_SHARE
    if level == "district":
        return "high" if sale_count >= 40 else "medium"
    if level == "city_rooms":
        return "high" if full and sale_count >= CITY_ROOMS_HIGH_MIN_SALE and rent_count >= CITY_ROOMS_HIGH_MIN_RENT else "medium"
    if level == "city":
        return "high" if full and sale_count >= CITY_HIGH_MIN_SALE and rent_count >= CITY_HIGH_MIN_RENT else "low"
    return "low"


def resolve_comparables(
    listing: Listing,
    index: GroupIndex,
    min_sale_sample: int = 15,
    min_rent_sample: int = 10,
    sample_share: float | None = None,
) -> ListingComparables | None:
    """Sale and rent fall back independently; None if no level has enough sales to score against."""
    keys = group_keys(listing)
    sale = next(((lvl, index.sale[(lvl, k)]) for lvl, k in keys
                 if len(index.sale.get((lvl, k), [])) >= min_sale_sample), None)
    if sale is None:
        return None
    rent = next(((lvl, index.rent[(lvl, k)]) for lvl, k in keys
                 if len(index.rent.get((lvl, k), [])) >= min_rent_sample), (None, []))

    sale_level, sale_listings = sale
    rent_level, rent_listings = rent
    worse = max(LEVELS.index(sale_level), LEVELS.index(rent_level) if rent_level else len(LEVELS))
    worse_level = LEVELS[worse] if worse < len(LEVELS) else None
    return ListingComparables(
        sale_level=sale_level,
        sale_listings=sale_listings,
        rent_level=rent_level,
        rent_listings=rent_listings,
        confidence=_confidence(worse_level, len(sale_listings), len(rent_listings), sample_share),
    )


def compute_groups(
    listings: list[Listing],
    min_sale_sample: int = 15,
    min_rent_sample: int = 10,
    sample_share: float | None = None,
) -> list[GroupStats]:
    """areaYield groups: every group, at any level, where both thresholds hold at that level."""
    index = index_groups(listings)
    results: list[GroupStats] = []
    for (level, key), sales in index.sale.items():
        rents = index.rent.get((level, key), [])
        if len(sales) < min_sale_sample or len(rents) < min_rent_sample:
            continue
        country, city, district, rooms = key
        results.append(GroupStats(
            country=country,
            city=city,
            district=district,
            rooms_bucket=rooms or "all",
            group_level=level,
            confidence=_confidence(level, len(sales), len(rents), sample_share),
            sale_listings=sales,
            rent_listings=rents,
            sale_price_per_m2=[ls.price_local / ls.area_m2 for ls in sales],
            rent_per_m2=[ls.price_local / ls.area_m2 for ls in rents],
        ))
    results.sort(key=lambda g: (g.country, g.city, LEVELS.index(g.group_level), g.district or "", g.rooms_bucket))
    return results


def gate_coverage(
    listings: list[Listing],
    min_sale_sample: int = 15,
    min_rent_sample: int = 10,
) -> dict[str, dict]:
    """§13 gate (binding): share of ALL cleaned sale listings per city scored at district level."""
    index = index_groups(listings)
    result: dict[str, dict] = {}
    for ls in listings:
        if ls.transaction != "sale":
            continue
        c = result.setdefault(ls.city, {"saleListings": 0, "scored": 0, "districtLevel": 0})
        c["saleListings"] += 1
        comp = resolve_comparables(ls, index, min_sale_sample, min_rent_sample)
        if comp is None:
            continue
        c["scored"] += 1
        c["districtLevel"] += comp.sale_level == "district"
    for c in result.values():
        c["districtLevelPct"] = round(c["districtLevel"] / c["saleListings"] * 100, 1)
    return result


def listing_rooms_bucket(ls: Listing) -> str | None:
    """Rooms bucket of a listing; None (city level only) when its room count looks wrong (suspectRooms)."""
    return None if "suspectRooms" in ls.flags else rooms_bucket(ls.rooms)


def rooms_bucket(rooms: int | None) -> str | None:
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
    """§13 gate (informational): share of observed district x rooms groups meeting both thresholds."""
    counts: dict[str, dict[tuple[str, str], dict[str, int]]] = {}
    for ls in listings:
        rb = listing_rooms_bucket(ls)
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


@dataclass
class SideCoverage:
    """What one market side fetched versus what Otodom reports (totalItems)."""
    fetched: int
    total: int | None
    fetched_by_district: dict[str, int] = field(default_factory=dict)
    total_by_district: dict[str, int] = field(default_factory=dict)
    primary_market_units: int = 0

    def reachable(self) -> int | None:
        return reachable_items(self.total, self.primary_market_units, self.fetched)

    def share(self) -> float | None:
        reach = self.reachable()
        return min(self.fetched / reach, 1.0) if reach else None


def reachable_items(total: int | None, primary_market_units: int, fetched: int) -> int | None:
    """Listings that can be fetched one by one: the portal total minus the flats inside development tiles."""
    if not total:
        return None
    return max(total - primary_market_units, fetched)


def sample_stats(
    listings: list[Listing],
    as_of: date,
    fetched: int,
    total: int | None,
    primary_market_units: int = 0,
) -> dict:
    """Age of the sample (LATEST sorting samples current supply) and its share of all listings."""
    reach = reachable_items(total, primary_market_units, fetched)
    ages = [max((as_of - ls.first_published).days, 0) for ls in listings if ls.first_published]
    return {
        "medianAgeDays": round(statistics.median(ages), 1) if ages else None,
        "oldestListingDays": max(ages) if ages else None,
        "share": round(min(fetched / reach, 1.0), 3) if reach else None,
        "fetched": fetched,
        "totalItems": total,
        "primaryMarketUnits": primary_market_units if total else None,
        "reachableItems": reach,
    }


def area_sample(
    group: GroupStats,
    as_of: date,
    coverage: dict[str, SideCoverage],
) -> dict:
    """Per side; share is the district's for district-level groups (Otodom totals have no rooms split)."""
    result = {}
    for side, listings in (("sale", group.sale_listings), ("rent", group.rent_listings)):
        cov = coverage.get(side)
        if cov is None:
            result[side] = sample_stats(listings, as_of, 0, None)
        elif group.group_level == "district":
            result[side] = sample_stats(
                listings, as_of,
                cov.fetched_by_district.get(group.district or "", 0),
                cov.total_by_district.get(group.district or ""),
            )
        else:
            result[side] = sample_stats(listings, as_of, cov.fetched, cov.total, cov.primary_market_units)
    return result


def sample_share(coverage: dict[str, SideCoverage]) -> float | None:
    """Share of the city's listings that was fetched: the smaller of the sale and rent side; None when unknown."""
    shares = [c.share() for c in coverage.values() if c.total]
    return min(shares) if len(shares) == len(coverage) and shares else None


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

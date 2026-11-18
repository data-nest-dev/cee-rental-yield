from __future__ import annotations

from datetime import datetime, timezone

from src.fx import convert_to_eur
from src.models import AreaYield, Listing, ScoredListing
from src.stats import (
    GroupStats, ListingComparables, deal_score, discount_vs_median_pct, gross_yield_pct,
    gross_yield_range, median_val, quartiles,
)


def build_area_yield(
    group: GroupStats,
    fx_rates: dict[str, float],
    fx_date: str,
    source_names: list[str],
    sample: dict | None = None,
) -> dict:
    currency = group.sale_listings[0].currency if group.sale_listings else "EUR"

    s_ppm2_eur = [convert_to_eur(p, currency, fx_rates) for p in group.sale_price_per_m2]
    r_ppm2_eur = [convert_to_eur(p, currency, fx_rates) for p in group.rent_per_m2]

    sq25, sq50, sq75 = quartiles(s_ppm2_eur)
    rq25, rq50, rq75 = quartiles(r_ppm2_eur)

    gyp = gross_yield_pct(rq50, sq50)
    gyr = gross_yield_range(rq25, rq75, sq25, sq75)

    rate = fx_rates.get(currency, 1.0)

    return {
        "recordType": "areaYield",
        "country": group.country,
        "city": group.city,
        "district": group.district,
        "rooms": group.rooms_bucket,
        "groupLevel": group.group_level,
        "confidence": group.confidence,
        "saleCount": len(group.sale_listings),
        "rentCount": len(group.rent_listings),
        "salePricePerM2Eur": {
            "median": round(sq50),
            "p25": round(sq25),
            "p75": round(sq75),
        },
        "rentPerM2MonthlyEur": {
            "median": round(rq50, 1),
            "p25": round(rq25, 1),
            "p75": round(rq75, 1),
        },
        "grossYieldPct": round(gyp, 2),
        "grossYieldRangePct": [round(gyr[0], 2), round(gyr[1], 2)],
        "local": {
            "currency": currency,
            "salePricePerM2Median": round(median_val(group.sale_price_per_m2)),
            "rentPerM2Median": round(median_val(group.rent_per_m2), 1),
        },
        "fx": {
            "source": "ECB",
            "date": fx_date,
            "eurToLocal": round(rate, 4) if currency != "EUR" else 1.0,
        },
        "priceBasis": "asking",
        "sample": sample,
        "sources": source_names,
        "computedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def build_scored_listing(
    listing: Listing,
    comparables: ListingComparables,
    fx_rates: dict[str, float],
) -> dict:
    price_eur = convert_to_eur(listing.price_local, listing.currency, fx_rates)
    ppm2_eur = price_eur / listing.area_m2

    s_ppm2_eur = [
        convert_to_eur(ls.price_local / ls.area_m2, ls.currency, fx_rates)
        for ls in comparables.sale_listings
    ]
    median_ppm2 = median_val(s_ppm2_eur)

    est_rent = None
    gyp = None
    if comparables.rent_level is not None:
        r_ppm2_eur = [
            convert_to_eur(ls.price_local / ls.area_m2, ls.currency, fx_rates)
            for ls in comparables.rent_listings
        ]
        est_rent = median_val(r_ppm2_eur) * listing.area_m2
        gyp = 12 * est_rent / price_eur * 100 if price_eur > 0 else None
    score = deal_score(ppm2_eur, s_ppm2_eur)
    discount = discount_vs_median_pct(ppm2_eur, median_ppm2)

    dom = None
    if listing.first_published:
        from datetime import date
        dom = (date.today() - listing.first_published).days

    return {
        "recordType": "scoredListing",
        "source": listing.source,
        "listingId": listing.listing_id,
        "url": listing.url,
        "country": listing.country,
        "city": listing.city,
        "district": listing.district,
        "rooms": listing.rooms,
        "areaM2": listing.area_m2,
        "isPrimaryMarket": listing.is_primary_market,
        "price": {
            "local": listing.price_local,
            "currency": listing.currency,
            "eur": round(price_eur),
        },
        "pricePerM2Eur": round(ppm2_eur),
        "groupMedianPricePerM2Eur": round(median_ppm2),
        "dealScore": score,
        "discountVsMedianPct": round(discount, 2),
        "estimatedRentMonthlyEur": round(est_rent) if est_rent is not None else None,
        "grossYieldPct": round(gyp, 2) if gyp is not None else None,
        "saleGroupLevel": comparables.sale_level,
        "rentGroupLevel": comparables.rent_level,
        "confidence": comparables.confidence,
        "daysOnMarket": dom,
    }


def build_side_summary(
    fetch_stats: dict,
    parse_rejected: dict[str, int],
    clean_rejected: dict[str, int],
    cleaned_count: int,
    requests: int,
    blocked: int,
    time_s: float,
    sample: dict | None = None,
) -> dict:
    """RUN_SUMMARY entry for one city x market side."""
    rejected = dict(parse_rejected)
    for reason, n in clean_rejected.items():
        rejected[reason] = rejected.get(reason, 0) + n
    projects = rejected.pop("primary_market_project", 0)
    return {
        "pages": fetch_stats.get("pages_fetched", 0),
        "rawItems": fetch_stats.get("raw_items", 0),
        "cleanedItems": cleaned_count,
        "rejected": rejected,
        "primaryMarketProjects": projects,
        "requests": requests,
        "blocked": blocked,
        "buildIdRefreshes": fetch_stats.get("build_id_refreshes", 0),
        "fallbackToHtml": fetch_stats.get("fallback_to_html", False),
        "districts": fetch_stats.get("districts"),
        "districtSource": fetch_stats.get("district_source"),
        "sample": sample,
        "timeS": round(time_s, 1),
    }

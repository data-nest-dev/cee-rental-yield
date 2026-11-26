"""mode listings: every sale and rent listing with analytics, one scored-listing event per row (offline)."""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src.inputs import parse_input
from tests.test_pipeline import FakeActor, FakeSource, PlatformPricedActor, _run

BASE = {"cities": ["katowice"], "mode": "listings", "minSaleSample": 2, "minRentSample": 2}
PERSONAL = ("advertOwner", "agency", "phone", "email", "title", "images", "street")


def test_listings_is_an_input_mode_and_the_default_is_unchanged() -> None:
    assert parse_input({"mode": "listings"}).wants_listings
    assert parse_input({}).mode == "both" and not parse_input({}).wants_listings


@pytest.mark.asyncio
async def test_rows_for_sale_and_rent_without_yield_rows_or_area_yield_events() -> None:
    actor, _, summary = await _run(BASE, actor=FakeActor(capacity={"scored-listing": 10_000, "area-yield": 10_000}))

    assert actor.failed is None and summary["status"] == "ok"
    rows = actor.records("listing")
    assert actor.records("areaYield") == [] and actor.records("scoredListing") == []
    assert {r["transaction"] for r in rows} == {"sale", "rent"}
    assert {e for e, _ in actor.pushed} == {"scored-listing"}
    sale = [r for r in rows if r["transaction"] == "sale"]
    # sale and rent are interleaved, not "best deals first" and not all sales before all rent
    first_rent = next(i for i, r in enumerate(rows) if r["transaction"] == "rent")
    assert first_rent < len(sale)
    assert not any(k in json.dumps(rows).lower() for k in ("advertowner", "agency", "phone", "@"))


@pytest.mark.asyncio
async def test_sale_row_estimates_follow_the_comparable_group() -> None:
    actor, _, _ = await _run(BASE)
    sale = [r for r in actor.records("listing") if r["transaction"] == "sale"]
    estimated = [r for r in sale if r["estimatedMonthlyRentPln"] is not None]
    assert estimated
    for r in estimated:
        assert r["estimatedMonthlyRentPln"] % 10 == 0
        assert r["estimatedGrossYieldPct"] == round(12 * r["estimatedMonthlyRentPln"] / r["price"]["local"] * 100, 2)
        assert r["estimatedMonthlyRentEur"] > 0 and r["estimateNote"] is None
        assert r["confidence"] != "low" and r["comparable"]["sale"]["confidence"] == r["confidence"]
        c = r["comparable"]
        assert c["sale"]["groupLevel"] == r["saleGroupLevel"] and c["rent"]["groupLevel"] == r["rentGroupLevel"]
        assert c["sale"]["saleCount"] >= 2 and c["rent"]["rentCount"] >= 2
        assert c["sale"]["groupLevel"] == "city" or c["sale"]["rooms"] is not None
        assert "estimatedRentMonthlyEur" not in r and "grossYieldPct" not in r


@pytest.mark.asyncio
async def test_low_confidence_or_too_few_rents_give_null_estimates_with_a_note() -> None:
    # defaults (15 / 10) on the small fixtures: groups fall back to city level -> low confidence or no rent group
    actor, _, _ = await _run({**BASE, "minSaleSample": 15, "minRentSample": 10})
    sale = [r for r in actor.records("listing") if r["transaction"] == "sale"]
    assert sale
    nulls = [r for r in sale if r["estimatedMonthlyRentPln"] is None]
    assert nulls
    for r in nulls:
        assert r["estimatedMonthlyRentEur"] is None and r["estimatedGrossYieldPct"] is None and r["estimateNote"]
        assert r["comparable"] is None or r["comparable"]["sale"]["confidence"] == "low" or r["comparable"]["rent"]["groupLevel"] is None
    city = (await _run({**BASE, "minSaleSample": 15, "minRentSample": 10}))[2]["cities"]["katowice"]["listings"]
    assert city["withoutEstimate"] == len(nulls) and city["withEstimate"] == len(sale) - len(nulls)


@pytest.mark.asyncio
async def test_rent_rows_have_null_sale_fields_and_a_rent_per_m2() -> None:
    actor, _, _ = await _run(BASE)
    rent = [r for r in actor.records("listing") if r["transaction"] == "rent"]
    assert rent
    for r in rent:
        for k in ("dealScore", "discountVsMedianPct", "pricePerM2Eur", "estimatedMonthlyRentPln",
                  "estimatedGrossYieldPct", "comparable", "confidence", "estimateNote"):
            assert r[k] is None, k
        assert r["monthlyRentPerM2Eur"] > 0 and r["price"]["local"] > 0


@pytest.mark.asyncio
async def test_run_summary_counts_per_city_and_no_yield_report_groups() -> None:
    actor, _, summary = await _run(BASE, actor=FakeActor(capacity={"scored-listing": 10_000}))
    city = summary["cities"]["katowice"]["listings"]
    rows = actor.records("listing")
    assert city["saleRows"] + city["rentRows"] == len(rows) and city["rentRows"] > 0
    assert city["withEstimate"] + city["withoutEstimate"] == city["saleRows"]
    assert city["charged"] == len(rows) and "scoredExcludedOutliers" in city
    assert summary["records"]["areaYield"] == 0
    assert all(c["groups"] == [] for c in actor.kv["YIELD_REPORT"]["cities"].values())


@pytest.mark.asyncio
async def test_each_row_is_one_scored_listing_event_and_the_limit_is_respected() -> None:
    actor, _, summary = await _run(BASE, actor=PlatformPricedActor("0.01"))
    n = len(actor.records("listing"))
    assert actor.failed is None and actor.charges["scored-listing"] == n
    assert "area-yield" not in actor.charges
    assert actor.charged_usd < actor.max_usd and summary["chargeLimitReached"] is True
    assert n >= 1
    assert actor.records("areaYield") == []          # budget mode adds no yield rows in listings mode


@pytest.mark.asyncio
async def test_blocked_second_city_delivers_the_first_and_skips_the_rest() -> None:
    actor, _, summary = await _run(
        {**BASE, "cities": ["katowice", "warszawa"]}, FakeSource(blocked={"warszawa"}),
        actor=FakeActor(capacity={"scored-listing": 10_000}))
    assert actor.failed is None and summary["status"] == "partial"
    assert {r["city"] for r in actor.records("listing")} == {"Katowice"}
    assert summary["cities"]["warszawa"]["status"] == "failed"
    assert summary["cities"]["katowice"]["listings"]["charged"] > 0


@pytest.mark.asyncio
async def test_rent_estimate_group_always_has_at_least_min_rent_sample_rentals() -> None:
    for min_rent in (2, 3, 5, 10):
        actor, _, _ = await _run({**BASE, "minRentSample": min_rent})
        for r in actor.records("listing"):
            if r["estimatedMonthlyRentPln"] is not None:
                assert r["comparable"]["rent"]["rentCount"] >= min_rent, (min_rent, r["comparable"])
            elif r["transaction"] == "sale" and r["comparable"] and r["comparable"]["sale"]["confidence"] != "low":
                assert r["comparable"]["rent"]["groupLevel"] is None and r["estimateNote"]


@pytest.mark.asyncio
async def test_rent_group_falls_back_district_to_city_rooms_to_city() -> None:
    actor, _, _ = await _run({**BASE, "minRentSample": 4})
    levels = {r["comparable"]["rent"]["groupLevel"] for r in actor.records("listing")
              if r["transaction"] == "sale" and r["comparable"]}
    for r in actor.records("listing"):
        c = r["comparable"]
        if c and c["rent"]["groupLevel"]:
            assert c["rent"]["rentCount"] >= 4
            assert (c["rent"]["district"] is not None) == (c["rent"]["groupLevel"] == "district")
            assert (c["rent"]["rooms"] is None) == (c["rent"]["groupLevel"] == "city")
    assert levels


@pytest.mark.asyncio
async def test_sale_listings_without_a_comparable_group_are_returned_and_charged_with_null_analytics() -> None:
    # 15 sales needed, the fixture city has fewer: nothing can be compared
    actor, _, summary = await _run({**BASE, "minSaleSample": 500}, actor=FakeActor(capacity={"scored-listing": 10_000}))
    sale = [r for r in actor.records("listing") if r["transaction"] == "sale"]
    assert sale and actor.failed is None
    for r in sale:
        assert r["dealScore"] is None and r["comparable"] is None and r["estimatedMonthlyRentPln"] is None
        assert r["estimateNote"] and r["price"]["local"] > 0
    city = summary["cities"]["katowice"]["listings"]
    assert city["saleNotComparable"] == len(sale) == city["withoutEstimate"]
    assert city["charged"] == city["saleRows"] + city["rentRows"]
    # scoreListings keeps skipping them
    actor2, _, _ = await _run({**BASE, "mode": "scoreListings", "minSaleSample": 500})
    assert actor2.records("scoredListing") == []


@pytest.mark.asyncio
async def test_max_scored_listings_is_ignored_in_listings_mode() -> None:
    all_rows, _, _ = await _run(BASE)
    capped, _, _ = await _run({**BASE, "maxScoredListings": 3})
    assert len(capped.records("listing")) == len(all_rows.records("listing")) > 3
    scored, _, _ = await _run({**BASE, "mode": "scoreListings", "maxScoredListings": 3})
    assert len(scored.records("scoredListing")) == 3


SCORED_LISTING_KEYS = {
    "recordType", "source", "listingId", "url", "country", "city", "district", "rooms", "areaM2", "isPrimaryMarket",
    "price", "pricePerM2Eur", "groupMedianPricePerM2Eur", "dealScore", "discountVsMedianPct",
    "estimatedRentMonthlyEur", "grossYieldPct", "saleGroupLevel", "rentGroupLevel", "confidence", "daysOnMarket",
    "flags", "identicalListingIds", "firstSeenAt", "changeType", "priceCutPct",
}  # the key set of a scoredListing record at 58bbfec^ (before mode listings)
AREA_YIELD_KEYS = {
    "recordType", "country", "city", "district", "rooms", "groupLevel", "confidence", "saleCount", "rentCount",
    "salePricePerM2Eur", "rentPerM2MonthlyEur", "grossYieldPct", "grossYieldRangePct", "local", "fx", "priceBasis",
    "sample", "sources", "computedAt",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["scoreListings", "both", "yieldReport"])
async def test_other_modes_keep_exactly_their_record_keys(mode: str) -> None:
    actor, _, _ = await _run({"cities": ["katowice"], "mode": mode})
    for r in actor.records("scoredListing"):
        assert set(r) == SCORED_LISTING_KEYS
    for r in actor.records("areaYield"):
        assert set(r) == AREA_YIELD_KEYS
    assert actor.records("listing") == []


PERSONAL_KEYS = ("owner", "agency", "agent", "advertiser", "phone", "email", "contact", "seller", "name", "title", "image")


@pytest.mark.asyncio
async def test_listing_rows_carry_no_advertiser_fields_and_have_stable_key_sets() -> None:
    actor, _, _ = await _run(BASE)
    rows = actor.records("listing")
    keysets = {r["transaction"]: set(r) for r in rows}
    assert {len(set(map(frozenset, [set(r) for r in rows if r["transaction"] == t]))) for t in ("sale", "rent")} == {1}
    for keys in keysets.values():
        assert not [k for k in keys if any(p in k.lower() for p in PERSONAL_KEYS)], keys
    print("SALE KEYS", sorted(keysets["sale"]))
    print("RENT KEYS", sorted(keysets["rent"]))


@pytest.mark.asyncio
async def test_outlier_far_below_group_median_is_not_returned_not_charged_and_counted() -> None:
    victim: dict = {}

    def cheapen(items, tx):
        if tx != "sale":
            return
        flats = [it for it in items if it.get("totalPrice") and it.get("areaInSquareMeters")]
        ppm2 = sorted(it["totalPrice"]["value"] / it["areaInSquareMeters"] for it in flats)
        median = ppm2[len(ppm2) // 2]
        it = next(i for i in flats if abs(i["totalPrice"]["value"] / i["areaInSquareMeters"] - median) / median < 0.15)
        it["totalPrice"]["value"] = round(median * it["areaInSquareMeters"] * 0.45)  # >= 50% below the median
        victim["id"] = str(it["id"])

    opts = {**BASE, "minSaleSample": 3}
    base_actor, _, base_summary = await _run(opts, FakeSource(replicate=3), actor=PlatformPricedActor("5"))
    actor, _, summary = await _run(opts, FakeSource(replicate=3, mutate=cheapen), actor=PlatformPricedActor("5"))
    ids = {r["listingId"] for r in actor.records("listing")}
    assert victim["id"] not in ids
    base_n = base_summary["cities"]["katowice"]["scoredExcludedOutliers"]
    assert summary["cities"]["katowice"]["scoredExcludedOutliers"] == base_n + 1
    assert summary["cities"]["katowice"]["listings"]["scoredExcludedOutliers"] == base_n + 1
    assert summary["scoredExcludedOutliers"] == base_n + 1
    assert actor.charges["scored-listing"] == len(actor.records("listing"))


def _row(city: str, tx: str, n: int) -> tuple[None, dict]:
    return None, {"city": city, "transaction": tx, "id": f"{tx}{n}"}


def test_interleave_gives_a_representative_slice_of_both_sides() -> None:
    from src.pipeline import sort_listings
    rows = [_row("A", "sale", i) for i in range(30)] + [_row("A", "rent", i) for i in range(20)]
    first10 = [r["transaction"] for _, r in sort_listings(rows)[:10]]
    assert first10.count("sale") == 6 and first10.count("rent") == 4          # 3:2
    out = [r["id"] for _, r in sort_listings(rows)]
    assert [i for i in out if i.startswith("sale")] == [f"sale{i}" for i in range(30)]   # portal order kept
    assert [i for i in out if i.startswith("rent")] == [f"rent{i}" for i in range(20)]


@pytest.mark.asyncio
async def test_budget_cut_returns_both_sides_and_messages_speak_of_listings() -> None:
    actor, _, summary = await _run(BASE, actor=PlatformPricedActor("0.0108"))   # $0.001 per row: room for 10 rows
    rows = actor.records("listing")
    assert len(rows) == 10 and {r["transaction"] for r in rows} == {"sale", "rent"}
    assert summary["chargeLimitReached"] and "scored" not in summary["note"] and "best deals" not in summary["note"]
    assert "listings (sale" in summary["note"] and "rent" in summary["note"]
    assert "listings (sale" in actor.statuses[-1] and "scored" not in actor.statuses[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["scoreListings", "listings"])
async def test_large_discount_flag_above_30_percent(mode: str) -> None:
    actor, _, _ = await _run({**BASE, "mode": mode})
    rows = [r for r in actor.records("listing" if mode == "listings" else "scoredListing") if r.get("dealScore") is not None]
    assert rows
    for r in rows:
        assert ("large_discount" in r["flags"]) == (r["discountVsMedianPct"] > 30)
    assert any("large_discount" in r["flags"] for r in rows)


@pytest.mark.asyncio
async def test_primary_market_is_false_under_secondary_filter_in_both_modes() -> None:
    for mode, rtype in (("scoreListings", "scoredListing"), ("listings", "listing")):
        actor, _, _ = await _run({**BASE, "mode": mode, "includePrimaryMarket": False})
        assert {r["isPrimaryMarket"] for r in actor.records(rtype)} == {False}

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
    scores = [r["dealScore"] for r in sale]
    assert scores == sorted(scores, reverse=True)
    # sale rows come before rent rows
    assert [r["transaction"] for r in rows] == ["sale"] * len(sale) + ["rent"] * (len(rows) - len(sale))
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
        assert r["confidence"] != "low" and r["comparable"]["confidence"] == r["confidence"]
        c = r["comparable"]
        assert c["groupLevel"] == r["saleGroupLevel"] and c["rentCount"] >= 2 and c["saleCount"] >= 2
        assert c["groupLevel"] == "city" or c["rooms"] is not None
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
        assert r["comparable"]["confidence"] == "low" or r["comparable"]["rentGroupLevel"] is None
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
async def test_outliers_are_neither_returned_nor_charged() -> None:
    def cheapen(items, tx):
        if tx == "sale":
            for it in items[:1]:
                if it.get("totalPrice"):
                    it["totalPrice"]["value"] = 1
    base_actor, _, _ = await _run(BASE)
    actor, _, summary = await _run(BASE, FakeSource(mutate=cheapen))
    assert len(actor.records("listing")) <= len(base_actor.records("listing"))
    assert all("outlier" not in r["flags"] for r in actor.records("listing"))


@pytest.mark.asyncio
async def test_each_row_is_one_scored_listing_event_and_the_limit_is_respected() -> None:
    actor, _, summary = await _run(BASE, actor=PlatformPricedActor("0.02"))
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
async def test_example_rows_for_the_report(capsys) -> None:
    actor, _, _ = await _run(BASE)
    rows = actor.records("listing")
    sale = next(r for r in rows if r["transaction"] == "sale" and r["estimatedMonthlyRentPln"])
    rent = next(r for r in rows if r["transaction"] == "rent")
    print("SALE", json.dumps(sale, ensure_ascii=False))
    print("RENT", json.dumps(rent, ensure_ascii=False))

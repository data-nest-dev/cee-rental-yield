"""December round (CLAUDE.md section 20): new cities, run-ending blocks, excluded outliers, full-sample confidence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import CITIES
from src.http import PortalBlockedError
from src.stats import FULL_SAMPLE_SHARE, _confidence, compute_groups, index_groups, resolve_comparables, sample_share, SideCoverage

from tests.test_pipeline import FakeActor, FakeSource, _run
from tests.test_stats import _many

NEW_SLUGS = {
    "katowice": "slaskie/katowice/katowice/katowice",
    "szczecin": "zachodniopomorskie/szczecin/szczecin/szczecin",
    "gdynia": "pomorskie/gdynia/gdynia/gdynia",
    "rzeszow": "podkarpackie/rzeszow/rzeszow/rzeszow",
    "lublin": "lubelskie/lublin/lublin/lublin",
    "bydgoszcz": "kujawsko--pomorskie/bydgoszcz/bydgoszcz/bydgoszcz",
}


@pytest.mark.parametrize("key,path", NEW_SLUGS.items())
def test_city_slug(key: str, path: str) -> None:
    assert CITIES[key].location_path == path
    assert len(path.split("/")) == 4 and CITIES[key].country == "PL" and CITIES[key].currency == "PLN"


def test_input_schema_lists_exactly_the_configured_cities_with_titles() -> None:
    items = json.loads((Path(__file__).parent.parent / ".actor/input_schema.json").read_text())["properties"]["cities"]["items"]
    assert set(items["enum"]) == set(CITIES)
    assert len(items["enum"]) == len(items["enumTitles"])
    assert dict(zip(items["enum"], items["enumTitles"]))["bydgoszcz"] == "Bydgoszcz"


def test_prefill_is_unchanged() -> None:
    props = json.loads((Path(__file__).parent.parent / ".actor/input_schema.json").read_text())["properties"]
    assert props["cities"]["prefill"] == ["warszawa"]
    assert props["samplingMode"]["prefill"] == "city" and props["maxListingsPerSide"]["prefill"] == 360


@pytest.mark.asyncio
@pytest.mark.parametrize("city", ["szczecin", "gdynia", "rzeszow", "lublin", "bydgoszcz"])
async def test_new_city_runs_through_the_pipeline(city: str) -> None:
    actor, _, summary = await _run({"cities": [city], "mode": "scoreListings"})
    assert actor.failed is None and summary["cities"][city]["status"] == "ok"
    assert actor.records("scoredListing")


@pytest.mark.asyncio
async def test_portal_block_stops_the_run_and_skips_remaining_cities() -> None:
    class Blocking(FakeSource):
        async def fetch_listings(self, city_key, transaction, max_listings, max_per_district=None):
            self.calls.append((city_key, transaction, max_listings, max_per_district))
            if city_key == "krakow":
                raise PortalBlockedError("www.otodom.pl refused the request (HTTP 403; krakow sale).")
            return await super().fetch_listings(city_key, transaction, max_listings, max_per_district)

    source = Blocking()
    actor, _, summary = await _run({"cities": ["warszawa", "krakow", "wroclaw"], "mode": "scoreListings"}, source=source)
    assert {c for c, *_ in source.calls} == {"warszawa", "krakow"}  # wroclaw never requested
    assert summary["cities"]["krakow"]["status"] == "skipped" and "HTTP 403" in summary["cities"]["krakow"]["reason"]
    assert summary["cities"]["wroclaw"]["status"] == "skipped"
    assert "HTTP 403" in summary["blockedMessage"]
    assert actor.records("scoredListing")  # warszawa finished before the block and is delivered


@pytest.mark.asyncio
async def test_block_in_the_only_city_fails_the_run_with_the_message_and_no_records() -> None:
    class Blocking(FakeSource):
        async def fetch_listings(self, *a, **k):
            raise PortalBlockedError("www.otodom.pl refused the request (HTTP 429; katowice sale).")

    actor, _, summary = await _run({"cities": ["katowice"]}, source=Blocking())
    assert summary["status"] == "failed" and actor.failed and "HTTP 429" in actor.failed
    assert actor.pushed == []


@pytest.mark.asyncio
async def test_outlier_is_not_returned_and_counted_separately() -> None:
    base, _, _ = await _run({"cities": ["katowice"], "mode": "scoreListings", "maxScoredListings": 0})
    before = {r["listingId"] for r in base.records("scoredListing")}

    def crash_one_price(items, tx):
        if tx == "sale":
            target = next(it for it in items if it.get("totalPrice") and it.get("estate") == "FLAT")
            target["totalPrice"]["value"] = round(target["totalPrice"]["value"] * 0.1)

    actor, _, summary = await _run(
        {"cities": ["katowice"], "mode": "scoreListings", "maxScoredListings": 0}, FakeSource(mutate=crash_one_price),
    )
    after = actor.records("scoredListing")
    assert all("outlier" not in r["flags"] for r in after)
    assert summary["scoredExcludedOutliers"] >= 1
    assert summary["cities"]["katowice"]["scoredExcludedOutliers"] == summary["scoredExcludedOutliers"]
    assert len(after) < len(before)
    assert len(after) == summary["records"]["scoredListing"]


@pytest.mark.parametrize("level,sale,rent,share,expected", [
    ("district", 39, 10, None, "medium"),
    ("district", 40, 10, None, "high"),
    ("district", 40, 0, 0.1, "high"),
    ("city_rooms", 500, 500, None, "medium"),       # unknown share: as before
    ("city_rooms", 500, 500, 0.79, "medium"),       # sampled, not full
    ("city_rooms", 99, 30, 0.8, "medium"),
    ("city_rooms", 100, 29, 0.8, "medium"),
    ("city_rooms", 100, 30, 0.8, "high"),
    ("city", 500, 500, None, "low"),
    ("city", 500, 500, 0.5, "low"),
    ("city", 199, 50, 0.9, "low"),
    ("city", 200, 49, 0.9, "low"),
    ("city", 200, 50, 0.9, "high"),
    (None, 500, 500, 1.0, "low"),
])
def test_confidence_rule(level, sale, rent, share, expected) -> None:
    assert _confidence(level, sale, rent, share) == expected


def test_confidence_flows_through_resolve_and_groups() -> None:
    ls = _many([("sale", 4, "A", 3), ("sale", 100, "B", 3), ("rent", 30, "B", 3), ("rent", 5, "A", 3)])
    index = index_groups(ls)
    assert resolve_comparables(ls[0], index).confidence == "medium"
    assert resolve_comparables(ls[0], index, sample_share=FULL_SAMPLE_SHARE).confidence == "high"
    rows = [g for g in compute_groups(ls, sample_share=0.9) if g.group_level == "city_rooms"]
    assert [g.confidence for g in rows] == ["high"]
    rows = [g for g in compute_groups(ls, sample_share=0.5) if g.group_level == "city_rooms"]
    assert [g.confidence for g in rows] == ["medium"]


def test_sample_share_is_the_smaller_side_and_unknown_when_a_total_is_missing() -> None:
    assert sample_share({"sale": SideCoverage(80, 100), "rent": SideCoverage(90, 100)}) == 0.8
    assert sample_share({"sale": SideCoverage(80, 100), "rent": SideCoverage(90, None)}) is None


@pytest.mark.asyncio
async def test_block_midway_through_a_city_leaves_no_partial_numbers_or_events() -> None:
    class RentBlocked(FakeSource):
        async def fetch_listings(self, city_key, transaction, max_listings, max_per_district=None):
            if city_key == "krakow" and transaction == "rent":
                raise PortalBlockedError("www.otodom.pl refused the request (HTTP 403; krakow rent).")
            return await super().fetch_listings(city_key, transaction, max_listings, max_per_district)

    actor, _, summary = await _run({"cities": ["warszawa", "krakow"], "mode": "both"}, source=RentBlocked())
    assert summary["cities"]["krakow"]["status"] == "skipped" and summary["cities"]["krakow"]["sides"] == {}
    assert {r["city"] for r in actor.records("scoredListing") + actor.records("areaYield")} == {"Warszawa"}
    assert summary["status"] == "partial" and summary["blockedMessage"]


def test_readme_rules() -> None:
    import re
    text = (Path(__file__).parent.parent / "README.md").read_text()
    domains = set(re.findall(r"https?://([^/\s)\"]+)", text))
    assert all(d == "apify.com" or d.endswith(".apify.com") for d in domains), domains
    heading, body = text.split("\n", 1)
    assert heading == "# Otodom Scraper with Rental Yield & Deal Score – Poland"  # the only place the word is allowed
    assert len(re.findall(r"(?i)scraper", body)) == 0

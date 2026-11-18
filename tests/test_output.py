from __future__ import annotations

from datetime import date

from src.models import Listing
from src.output import build_area_yield, build_scored_listing
from src.stats import GroupStats


def _make_listing(transaction: str = "sale", **kwargs) -> Listing:
    defaults = dict(
        source="otodom",
        listing_id="1",
        dedup_key="slug-1",
        url="https://example.com/1",
        country="PL",
        city="Katowice",
        district="Bogucice",
        transaction=transaction,
        price_local=300000.0,
        currency="PLN",
        admin_fee_local=None,
        area_m2=50.0,
        rooms=2,
        floor=3,
        is_primary_market=False,
        advertiser_type="private",
        first_published=date(2026, 10, 1),
    )
    defaults.update(kwargs)
    return Listing(**defaults)


def _make_group() -> GroupStats:
    sales = [_make_listing("sale", listing_id=str(i), dedup_key=f"s{i}",
                           price_local=300000 + i * 1000)
             for i in range(20)]
    rents = [_make_listing("rent", listing_id=str(i), dedup_key=f"r{i}",
                           price_local=2000 + i * 50)
             for i in range(15)]
    return GroupStats(
        country="PL",
        city="Katowice",
        district="Bogucice",
        rooms_bucket="2",
        group_level="district",
        confidence="high",
        sale_listings=sales,
        rent_listings=rents,
        sale_price_per_m2=[ls.price_local / ls.area_m2 for ls in sales],
        rent_per_m2=[ls.price_local / ls.area_m2 for ls in rents],
    )


class TestBuildAreaYield:
    def test_record_type(self) -> None:
        group = _make_group()
        rates = {"PLN": 4.4}
        result = build_area_yield(group, rates, "2026-11-17", ["otodom"])
        assert result["recordType"] == "areaYield"
        assert result["country"] == "PL"
        assert result["city"] == "Katowice"
        assert result["district"] == "Bogucice"
        assert result["confidence"] == "high"

    def test_has_yield_fields(self) -> None:
        group = _make_group()
        rates = {"PLN": 4.4}
        result = build_area_yield(group, rates, "2026-11-17", ["otodom"])
        assert "grossYieldPct" in result
        assert result["grossYieldPct"] > 0
        assert len(result["grossYieldRangePct"]) == 2

    def test_has_local_currency(self) -> None:
        group = _make_group()
        rates = {"PLN": 4.4}
        result = build_area_yield(group, rates, "2026-11-17", ["otodom"])
        assert result["local"]["currency"] == "PLN"


class TestBuildScoredListing:
    def test_record_type(self) -> None:
        group = _make_group()
        ls = _make_listing("sale")
        rates = {"PLN": 4.4}
        result = build_scored_listing(ls, group, rates)
        assert result["recordType"] == "scoredListing"
        assert result["dealScore"] >= 0
        assert result["dealScore"] <= 100

    def test_has_yield_estimate(self) -> None:
        group = _make_group()
        ls = _make_listing("sale")
        rates = {"PLN": 4.4}
        result = build_scored_listing(ls, group, rates)
        assert result["estimatedRentMonthlyEur"] > 0
        assert result["grossYieldPct"] > 0

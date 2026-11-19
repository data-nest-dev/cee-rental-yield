from __future__ import annotations

from datetime import date

from src.models import Listing
from src.output import build_area_yield, build_scored_listing
from src.stats import GroupStats, ListingComparables


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


def _make_comparables(rent_level: str | None = "city_rooms") -> ListingComparables:
    g = _make_group()
    return ListingComparables(
        sale_level="district",
        sale_listings=g.sale_listings,
        rent_level=rent_level,
        rent_listings=g.rent_listings if rent_level else [],
        confidence="medium",
    )


class TestBuildScoredListing:
    def test_record_type(self) -> None:
        ls = _make_listing("sale")
        result = build_scored_listing(ls, _make_comparables(), {"PLN": 4.4})
        assert result["recordType"] == "scoredListing"
        assert 0 <= result["dealScore"] <= 100

    def test_has_yield_estimate(self) -> None:
        ls = _make_listing("sale")
        result = build_scored_listing(ls, _make_comparables(), {"PLN": 4.4})
        assert result["estimatedRentMonthlyEur"] > 0
        assert result["grossYieldPct"] > 0

    def test_reports_both_levels(self) -> None:
        ls = _make_listing("sale")
        result = build_scored_listing(ls, _make_comparables(), {"PLN": 4.4})
        assert result["saleGroupLevel"] == "district"
        assert result["rentGroupLevel"] == "city_rooms"
        assert "groupLevel" not in result

    def test_estimated_rent_hand_computed(self) -> None:
        # rents 2000..2700 PLN step 50 over 50 m2 -> median 2350 / 50 = 47 PLN/m2 -> /4.4 EUR; x 50 m2
        ls = _make_listing("sale", price_local=440000.0)
        result = build_scored_listing(ls, _make_comparables(), {"PLN": 4.4})
        assert result["estimatedRentMonthlyEur"] == round(47 / 4.4 * 50)
        assert result["grossYieldPct"] == round(12 * 47 * 50 / 440000 * 100, 2)

    def test_no_rent_level_means_no_yield_estimate(self) -> None:
        ls = _make_listing("sale")
        result = build_scored_listing(ls, _make_comparables(rent_level=None), {"PLN": 4.4})
        assert result["estimatedRentMonthlyEur"] is None
        assert result["grossYieldPct"] is None
        assert result["rentGroupLevel"] is None


class TestSideSummary:
    def test_primary_market_projects_and_merged_rejections(self) -> None:
        from src.output import build_side_summary
        summary = build_side_summary(
            fetch_stats={"pages_fetched": 3, "raw_items": 108, "build_id_refreshes": 1,
                         "fallback_to_html": False, "districts": 22, "district_source": "related_locations"},
            parse_rejected={"primary_market_project": 8, "ad_insert": 3, "outlier": 1},
            clean_rejected={"outlier": 2, "area_out_of_range": 1},
            cleaned_count=93, requests=4, blocked=0, time_s=4.04,
        )
        assert summary["primaryMarketProjects"] == 8
        assert summary["rejected"] == {"ad_insert": 3, "outlier": 3, "area_out_of_range": 1}
        assert summary["pages"] == 3
        assert summary["districtSource"] == "related_locations"
        assert summary["timeS"] == 4.0


class TestSampleInRecords:
    def test_area_yield_carries_sample(self) -> None:
        sample = {"sale": {"medianAgeDays": 4}, "rent": {"medianAgeDays": 9}}
        result = build_area_yield(_make_group(), {"PLN": 4.4}, "2026-11-17", ["otodom"], sample=sample)
        assert result["sample"] == sample

    def test_side_summary_carries_sample(self) -> None:
        from src.output import build_side_summary
        sample = {"medianAgeDays": 3, "oldestListingDays": 40, "share": 0.25}
        summary = build_side_summary({}, {}, {}, 0, 0, 0, 0.0, sample=sample)
        assert summary["sample"] == sample


class TestFlags:
    def _record(self, **kw) -> dict:
        return build_scored_listing(_make_listing("sale", **kw), _make_comparables(), {"PLN": 4.4})

    def test_ordinary_listing_has_no_flags(self) -> None:
        import statistics
        comps = _make_comparables()
        median = statistics.median(ls.price_local / ls.area_m2 for ls in comps.sale_listings)
        assert self._record(price_local=median * 50)["flags"] == []

    def test_deep_discount_is_flagged_outlier(self) -> None:
        assert "outlier" in self._record(price_local=1000.0)["flags"]

    def test_listing_flags_are_carried_over(self) -> None:
        import statistics
        comps = _make_comparables()
        median = statistics.median(ls.price_local / ls.area_m2 for ls in comps.sale_listings)
        rec = self._record(price_local=median * 50, flags=("needsRenovation",))
        assert rec["flags"] == ["needsRenovation"]

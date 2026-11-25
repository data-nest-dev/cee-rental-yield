from __future__ import annotations

import math
from datetime import date

from src.models import Listing
from src.stats import (
    compute_groups,
    deal_score,
    discount_vs_median_pct,
    district_group_coverage,
    gate_coverage,
    index_groups,
    resolve_comparables,
    gross_yield_pct,
    gross_yield_range,
    median_val,
    quartiles,
)


class TestMedianAndQuartiles:
    def test_median_odd(self) -> None:
        assert median_val([1, 2, 3]) == 2.0

    def test_median_even(self) -> None:
        assert median_val([1, 2, 3, 4]) == 2.5

    def test_median_empty(self) -> None:
        assert median_val([]) == 0.0

    def test_quartiles_basic(self) -> None:
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        q1, q2, q3 = quartiles(data)
        assert q2 == 5.5
        assert q1 < q2 < q3

    def test_quartiles_single_element(self) -> None:
        q1, q2, q3 = quartiles([42.0])
        assert q1 == q2 == q3 == 42.0


class TestGrossYield:
    def test_basic_yield(self) -> None:
        # rent/m2 = 15, sale/m2 = 3000 → 12*15/3000*100 = 6.0%
        assert abs(gross_yield_pct(15.0, 3000.0) - 6.0) < 0.01

    def test_zero_sale_price(self) -> None:
        assert gross_yield_pct(15.0, 0.0) == 0.0

    def test_yield_range(self) -> None:
        result = gross_yield_range(12.0, 18.0, 2800.0, 3200.0)
        # low = 12*12/3200*100 = 4.5, high = 12*18/2800*100 = 7.71...
        assert abs(result[0] - 4.5) < 0.01
        assert abs(result[1] - 7.714) < 0.01


class TestDealScore:
    def test_median_price_scores_50(self) -> None:
        prices = [100.0] * 20
        assert deal_score(100.0, prices) == 50

    def test_cheap_scores_high(self) -> None:
        prices = [100.0 + i for i in range(50)]
        score = deal_score(80.0, prices)
        assert score > 70

    def test_expensive_scores_low(self) -> None:
        prices = [100.0 + i for i in range(50)]
        score = deal_score(200.0, prices)
        assert score < 20

    def test_mad_zero_equal_to_median(self) -> None:
        prices = [100.0] * 20
        assert deal_score(100.0, prices) == 50

    def test_mad_zero_cheaper_than_median(self) -> None:
        prices = [100.0] * 20
        assert deal_score(80.0, prices) == 100

    def test_mad_zero_more_expensive(self) -> None:
        prices = [100.0] * 20
        assert deal_score(120.0, prices) == 0

    def test_single_listing(self) -> None:
        assert deal_score(100.0, [100.0]) == 50

    def test_empty_list(self) -> None:
        assert deal_score(100.0, []) == 50


class TestDiscountVsMedian:
    def test_below_median(self) -> None:
        # (3000 - 2700) / 3000 * 100 = 10%
        assert abs(discount_vs_median_pct(2700.0, 3000.0) - 10.0) < 0.01

    def test_above_median(self) -> None:
        result = discount_vs_median_pct(3300.0, 3000.0)
        assert result < 0

    def test_equal_to_median(self) -> None:
        assert discount_vs_median_pct(3000.0, 3000.0) == 0.0


def _cov_listing(tx: str, district: str | None, rooms: int | None, i: int) -> Listing:
    return Listing(
        source="otodom", listing_id=str(i), dedup_key=f"s{i}", url="u", country="PL",
        city="Katowice", district=district, transaction=tx, price_local=1.0, currency="PLN",
        admin_fee_local=None, area_m2=50.0, rooms=rooms, floor=None, is_primary_market=False,
        advertiser_type=None, first_published=date(2026, 1, 1),
    )


class TestDistrictGroupCoverage:
    def test_counts_groups_meeting_both_thresholds(self) -> None:
        ls = []
        i = 0
        for tx, n, district, rooms in [
            ("sale", 15, "A", 2), ("rent", 10, "A", 2),  # full
            ("sale", 14, "A", 3), ("rent", 30, "A", 3),  # sale short
            ("sale", 40, "B", 5), ("rent", 9, "B", 4),   # 4+ bucket, rent short
        ]:
            for _ in range(n):
                i += 1
                ls.append(_cov_listing(tx, district, rooms, i))
        cov = district_group_coverage(ls)["Katowice"]
        assert cov == {"groups": 3, "fullGroups": 1, "coveragePct": 33.3}

    def test_skips_listings_without_district_or_rooms(self) -> None:
        ls = [_cov_listing("sale", None, 2, 1), _cov_listing("rent", "A", None, 2)]
        assert district_group_coverage(ls) == {}


def _many(spec: list[tuple[str, int, str | None, int | None]]) -> list[Listing]:
    out, i = [], 0
    for tx, n, district, rooms in spec:
        for _ in range(n):
            i += 1
            out.append(_cov_listing(tx, district, rooms, i))
    return out


class TestIndependentFallback:
    def test_sale_and_rent_resolve_to_different_levels(self) -> None:
        # A/2: 20 sales but 3 rents; B/2 adds 10 rents -> city x 2 rooms has 13 rents
        ls = _many([("sale", 20, "A", 2), ("rent", 3, "A", 2), ("rent", 10, "B", 2)])
        comp = resolve_comparables(ls[0], index_groups(ls))
        assert comp.sale_level == "district"
        assert len(comp.sale_listings) == 20
        assert comp.rent_level == "city_rooms"
        assert len(comp.rent_listings) == 13
        assert comp.confidence == "medium"  # worse of the two levels

    def test_rent_count_does_not_affect_sale_level(self) -> None:
        ls = _many([("sale", 15, "A", 2)])
        comp = resolve_comparables(ls[0], index_groups(ls))
        assert comp.sale_level == "district"
        assert comp.rent_level is None
        assert comp.rent_listings == []
        assert comp.confidence == "low"

    def test_confidence_high_needs_40_sales_at_district(self) -> None:
        ls39 = _many([("sale", 39, "A", 2), ("rent", 10, "A", 2)])
        ls40 = _many([("sale", 40, "A", 2), ("rent", 10, "A", 2)])
        assert resolve_comparables(ls39[0], index_groups(ls39)).confidence == "medium"
        assert resolve_comparables(ls40[0], index_groups(ls40)).confidence == "high"

    def test_sale_falls_back_to_city_rooms_then_city(self) -> None:
        # A/3 has 4 sales; 3-room total in city = 16 -> city_rooms
        ls = _many([("sale", 4, "A", 3), ("sale", 12, "B", 3), ("sale", 5, "C", 2)])
        assert resolve_comparables(ls[0], index_groups(ls)).sale_level == "city_rooms"
        # 2-room listings: city x 2 has 5 -> city level (21 sales)
        assert resolve_comparables(ls[-1], index_groups(ls)).sale_level == "city"

    def test_unknown_rooms_only_city_level(self) -> None:
        ls = _many([("sale", 15, "A", None)])
        assert resolve_comparables(ls[0], index_groups(ls)).sale_level == "city"

    def test_not_scoreable_without_enough_sales_anywhere(self) -> None:
        ls = _many([("sale", 14, "A", 2), ("rent", 50, "A", 2)])
        assert resolve_comparables(ls[0], index_groups(ls)) is None


class TestComputeGroups:
    def test_area_yield_requires_both_thresholds_at_same_level(self) -> None:
        ls = _many([("sale", 20, "A", 2), ("rent", 3, "A", 2), ("rent", 10, "B", 2)])
        groups = compute_groups(ls)
        assert [(g.group_level, g.district, g.rooms_bucket) for g in groups] == [
            ("city_rooms", None, "2"),
            ("city", None, "all"),
        ]
        assert [g.confidence for g in groups] == ["medium", "low"]
        assert (len(groups[0].sale_listings), len(groups[0].rent_listings)) == (20, 13)

    def test_district_group_emitted_when_both_thresholds_met(self) -> None:
        ls = _many([("sale", 40, "A", 2), ("rent", 10, "A", 2)])
        district = [g for g in compute_groups(ls) if g.group_level == "district"]
        assert len(district) == 1
        assert district[0].district == "A"
        assert district[0].confidence == "high"


class TestGateCoverage:
    def test_share_of_scored_sales_at_district_level(self) -> None:
        ls = _many([
            ("sale", 20, "A", 2),    # district
            ("sale", 16, "C", 3),    # district
            ("sale", 4, "D", 3),     # city_rooms (3 rooms: 20 in city)
            ("sale", 1, "A", None),  # city
        ])
        cov = gate_coverage(ls)["Katowice"]
        assert cov == {"saleListings": 41, "scored": 41, "districtLevel": 36, "districtLevelPct": 87.8}

    def test_city_level_fallback_counts_as_not_district(self) -> None:
        # 20 district-level sales + 10 sales without district/rooms (scored at city level)
        ls = _many([("sale", 20, "A", 2), ("sale", 10, None, None)])
        cov = gate_coverage(ls)["Katowice"]
        assert (cov["saleListings"], cov["scored"], cov["districtLevel"]) == (30, 30, 20)
        assert cov["districtLevelPct"] == 66.7

    def test_unscoreable_sales_stay_in_denominator(self) -> None:
        # 14 sales: no level reaches 15, nothing is scored; the city reports 0%, not nothing
        ls = _many([("sale", 14, "A", 2), ("rent", 30, "A", 2)])
        assert gate_coverage(ls)["Katowice"] == {
            "saleListings": 14, "scored": 0, "districtLevel": 0, "districtLevelPct": 0.0,
        }

    def test_with_15_city_sales_every_sale_is_scoreable(self) -> None:
        # The city level holds every sale, so unscoreable sales only occur in cities under 15.
        ls = _many([("sale", 1, "A", 2), ("sale", 1, "B", 3), ("sale", 13, None, None)])
        cov = gate_coverage(ls)["Katowice"]
        assert cov["scored"] == cov["saleListings"] == 15


class TestSampleAge:
    AS_OF = date(2026, 11, 18)

    def _aged(self, days: list[int | None], tx: str = "sale", district: str = "A") -> list[Listing]:
        out = []
        for i, d in enumerate(days):
            ls = _cov_listing(tx, district, 2, i)
            ls.first_published = None if d is None else date.fromordinal(self.AS_OF.toordinal() - d)
            out.append(ls)
        return out

    def test_median_oldest_and_share(self) -> None:
        from src.stats import sample_stats
        s = sample_stats(self._aged([1, 3, 10, None]), self.AS_OF, fetched=300, total=1200)
        assert s == {"medianAgeDays": 3, "oldestListingDays": 10, "share": 0.25,
                     "fetched": 300, "totalItems": 1200,
                     "primaryMarketUnits": 0, "reachableItems": 1200}

    def test_unknown_total_and_no_dates(self) -> None:
        from src.stats import sample_stats
        s = sample_stats(self._aged([None]), self.AS_OF, fetched=5, total=None)
        assert s["medianAgeDays"] is None and s["oldestListingDays"] is None and s["share"] is None

    def test_future_publication_counts_as_zero_days(self) -> None:
        from src.stats import sample_stats
        assert sample_stats(self._aged([-2, 4]), self.AS_OF, 2, 2)["medianAgeDays"] == 2

    def test_area_sample_uses_district_or_city_scope(self) -> None:
        from src.stats import SideCoverage, area_sample
        ls = self._aged([2] * 15, "sale", "A") + self._aged([6] * 10, "rent", "A")
        cov = {
            "sale": SideCoverage(fetched=600, total=2000, fetched_by_district={"A": 150}, total_by_district={"A": 300}),
            "rent": SideCoverage(fetched=400, total=800, fetched_by_district={"A": 40}, total_by_district={}),
        }
        groups = {g.group_level: g for g in compute_groups(ls)}
        district = area_sample(groups["district"], self.AS_OF, cov)
        assert district["sale"]["share"] == 0.5 and district["sale"]["medianAgeDays"] == 2
        assert district["rent"]["share"] is None  # district total unknown (city-wide mode)
        assert district["rent"]["medianAgeDays"] == 6
        city = area_sample(groups["city_rooms"], self.AS_OF, cov)
        assert city["sale"]["share"] == 0.3 and city["rent"]["share"] == 0.5


class TestReachableShare:
    def test_units_in_development_tiles_leave_the_denominator(self) -> None:
        from src.stats import sample_stats
        s = sample_stats([], date(2026, 11, 18), fetched=2468, total=3131, primary_market_units=663)
        assert (s["reachableItems"], s["primaryMarketUnits"], s["share"]) == (2468, 663, 1.0)

    def test_reachable_never_below_fetched_and_share_capped_at_one(self) -> None:
        from src.stats import sample_stats
        s = sample_stats([], date(2026, 11, 18), fetched=900, total=1000, primary_market_units=500)
        assert (s["reachableItems"], s["share"]) == (900, 1.0)

    def test_without_tiles_share_is_as_before(self) -> None:
        from src.stats import sample_stats
        assert sample_stats([], date(2026, 11, 18), fetched=300, total=1200)["share"] == 0.25

    def test_city_confidence_is_high_when_the_reachable_share_is_full(self) -> None:
        from src.stats import FULL_SAMPLE_SHARE, SideCoverage, _confidence, sample_share
        cov = {"sale": SideCoverage(2468, 3131, primary_market_units=663), "rent": SideCoverage(329, 329)}
        share = sample_share(cov)
        assert share == 1.0 and share >= FULL_SAMPLE_SHARE
        assert _confidence("city", 2000, 300, share) == "high"
        # same fetch without the tile correction would have been 0.79 -> low
        assert sample_share({"sale": SideCoverage(2468, 3131), "rent": SideCoverage(329, 329)}) < FULL_SAMPLE_SHARE

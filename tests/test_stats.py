from __future__ import annotations

import math
from datetime import date

from src.models import Listing
from src.stats import (
    deal_score,
    discount_vs_median_pct,
    district_group_coverage,
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

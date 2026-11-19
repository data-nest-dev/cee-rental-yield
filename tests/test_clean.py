from __future__ import annotations

from datetime import date

from src.clean import clean_listings
from src.models import Listing


def _make_listing(**kwargs) -> Listing:
    defaults = dict(
        source="otodom",
        listing_id="1",
        dedup_key="slug-1",
        url="https://example.com/1",
        country="PL",
        city="Katowice",
        district="Bogucice",
        transaction="sale",
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


class TestCleanListings:
    def test_keeps_valid_listing(self) -> None:
        ls = [_make_listing()]
        result, rejected = clean_listings(ls)
        assert len(result) == 1
        assert not rejected

    def test_rejects_too_small_area(self) -> None:
        ls = [_make_listing(area_m2=10.0)]
        result, rejected = clean_listings(ls)
        assert len(result) == 0
        assert rejected["area_out_of_range"] == 1

    def test_rejects_too_large_area(self) -> None:
        ls = [_make_listing(area_m2=300.0)]
        result, rejected = clean_listings(ls)
        assert len(result) == 0
        assert rejected["area_out_of_range"] == 1

    def test_dedup_across_calls(self) -> None:
        ls = [_make_listing(), _make_listing()]
        result, rejected = clean_listings(ls)
        assert len(result) == 1
        assert rejected["duplicate"] == 1

    def test_outlier_removal(self) -> None:
        # Create 100 listings with similar prices and 1 extreme outlier
        normal = [
            _make_listing(
                listing_id=str(i),
                dedup_key=f"slug-{i}",
                price_local=300000.0 + i * 100,
            )
            for i in range(100)
        ]
        outlier = _make_listing(
            listing_id="999",
            dedup_key="slug-999",
            price_local=50000000.0,  # extreme
        )
        result, rejected = clean_listings(normal + [outlier])
        ids = {ls.listing_id for ls in result}
        assert "999" not in ids
        assert rejected.get("outlier", 0) >= 1

    def test_boundary_area_accepted(self) -> None:
        ls = [
            _make_listing(listing_id="1", dedup_key="a", area_m2=15.0),
            _make_listing(listing_id="2", dedup_key="b", area_m2=250.0),
        ]
        result, _ = clean_listings(ls)
        assert len(result) == 2


class TestNearDuplicates:
    def test_rent_reposts_of_the_same_unit_count_once(self) -> None:
        """Praga-Północ case: 5 x 115 m2 / 18 000 PLN posted under different slugs."""
        reposts = [
            _make_listing(transaction="rent", dedup_key=f"r{i}", listing_id=str(i), district="Praga-Północ",
                          rooms=4, area_m2=115.0, price_local=18000.0, floor=2, advertiser_type="business")
            for i in range(5)
        ]
        other = _make_listing(transaction="rent", dedup_key="o", district="Praga-Północ", rooms=4,
                              area_m2=100.0, price_local=18000.0, floor=2, advertiser_type="business")
        result, rejected = clean_listings(reposts + [other])
        assert len(result) == 2
        assert rejected["near_duplicate_rent"] == 4

    def test_missing_fields_compare_as_empty(self) -> None:
        a = _make_listing(transaction="rent", dedup_key="a", floor=None, advertiser_type=None)
        b = _make_listing(transaction="rent", dedup_key="b", floor=None, advertiser_type=None)
        c = _make_listing(transaction="rent", dedup_key="c", floor=1, advertiser_type=None)
        result, rejected = clean_listings([a, b, c])
        assert [x.dedup_key for x in result] == ["a", "c"]
        assert rejected["near_duplicate_rent"] == 1

    def test_sale_twins_are_only_counted(self) -> None:
        twins = [_make_listing(dedup_key=f"s{i}", listing_id=str(i)) for i in range(3)]
        counters: dict[str, int] = {}
        result, rejected = clean_listings(twins, counters=counters)
        assert len(result) == 3
        assert "near_duplicate_sale" not in rejected
        assert counters == {"near_duplicate_sale": 2}

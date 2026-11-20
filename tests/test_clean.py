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

    def test_identical_sale_listings_merge_into_the_lowest_listing_id(self) -> None:
        twins = [_make_listing(dedup_key=f"s{i}", listing_id=i) for i in ("10", "9", "100")]
        other = _make_listing(dedup_key="o", listing_id="1", price_local=999999.0)
        counters: dict[str, int] = {}
        result, rejected = clean_listings(twins + [other], counters=counters)
        assert [x.listing_id for x in result] == ["9", "1"]  # numeric order: 9 < 10 < 100
        assert result[0].identical_ids == ("10", "100") and result[0].identical_keys == ("s10", "s100")
        assert result[1].identical_ids == ()
        assert counters == {"identical_merged": 2} and "near_duplicate_sale" not in rejected

    def test_sale_listings_differing_in_district_rooms_area_or_price_are_not_merged(self) -> None:
        base = dict(district="Ursus", rooms=2, area_m2=40.0, price_local=400000.0)
        variants = [_make_listing(dedup_key="a", listing_id="1", **base),
                    _make_listing(dedup_key="b", listing_id="2", **{**base, "district": "Wola"}),
                    _make_listing(dedup_key="c", listing_id="3", **{**base, "rooms": 3}),
                    _make_listing(dedup_key="d", listing_id="4", **{**base, "area_m2": 41.0}),
                    _make_listing(dedup_key="e", listing_id="5", **{**base, "price_local": 410000.0})]
        result, _ = clean_listings(variants)
        assert len(result) == 5

    def test_rent_twins_are_not_merged_as_sales(self) -> None:
        rents = [_make_listing(transaction="rent", dedup_key=f"r{i}", listing_id=str(i), floor=i) for i in range(2)]
        result, rejected = clean_listings(rents)
        assert len(result) == 2 and not rejected

    def test_suspect_rooms_flag_when_less_than_8_m2_per_room(self) -> None:
        odd = _make_listing(dedup_key="x", listing_id="1", rooms=7, area_m2=27.0)
        edge = _make_listing(dedup_key="y", listing_id="2", rooms=3, area_m2=24.0, price_local=300001.0)  # exactly 8
        none = _make_listing(dedup_key="z", listing_id="3", rooms=None, area_m2=20.0, price_local=300002.0)
        result, _ = clean_listings([odd, edge, none])
        by_key = {x.dedup_key: x for x in result}
        assert "suspectRooms" in by_key["x"].flags and by_key["x"].rooms == 7
        assert "suspectRooms" not in by_key["y"].flags and "suspectRooms" not in by_key["z"].flags

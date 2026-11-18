from __future__ import annotations

import json
from pathlib import Path

from src.config import CITIES
from src.sources.sreality import (
    _find_estates_in_dehydrated,
    _parse_area,
    parse_sreality_items,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    data = json.loads((FIXTURE_DIR / name).read_text())
    pp = data.get("pageProps", {})
    return _find_estates_in_dehydrated(pp)


class TestSrealitySaleParsing:
    def setup_method(self) -> None:
        self.raw = _load_fixture("sreality_sale_brno.json")
        self.cfg = CITIES["brno"]

    def test_parses_valid_listings(self) -> None:
        listings, rejected = parse_sreality_items(self.raw, self.cfg, "sale")
        assert len(listings) > 0
        for ls in listings:
            assert ls.source == "sreality"
            assert ls.transaction == "sale"
            assert ls.country == "CZ"
            assert ls.price_local > 0
            assert ls.area_m2 > 0

    def test_city_part_as_district(self) -> None:
        listings, _ = parse_sreality_items(self.raw, self.cfg, "sale")
        with_district = [ls for ls in listings if ls.district]
        assert len(with_district) > 0

    def test_rooms_from_category_sub(self) -> None:
        listings, _ = parse_sreality_items(self.raw, self.cfg, "sale")
        rooms_seen = {ls.rooms for ls in listings if ls.rooms is not None}
        assert rooms_seen

    def test_dedup_by_id(self) -> None:
        listings, _ = parse_sreality_items(self.raw, self.cfg, "sale")
        ids = [ls.listing_id for ls in listings]
        assert len(ids) == len(set(ids))

    def test_rejects_placeholder_prices(self) -> None:
        """Price 0 or 1 should be rejected"""
        fake = [{"id": 999, "name": "Prodej bytu 2+kk 50 m²",
                 "priceCzk": 1, "priceCzkPerSqM": 0,
                 "locality": {"city": "Brno", "cityPart": "Test"},
                 "categorySubCb": {"name": "2+kk", "value": 4},
                 "categoryTypeCb": {"name": "Prodej", "value": 1},
                 "categoryMainCb": {"name": "Byty", "value": 1}}]
        listings, rejected = parse_sreality_items(fake, self.cfg, "sale")
        assert len(listings) == 0
        assert rejected.get("placeholder_price", 0) >= 1


class TestSrealityRentParsing:
    def setup_method(self) -> None:
        self.raw = _load_fixture("sreality_rent_brno.json")
        self.cfg = CITIES["brno"]

    def test_parses_rent_listings(self) -> None:
        listings, rejected = parse_sreality_items(self.raw, self.cfg, "rent")
        assert len(listings) > 0
        for ls in listings:
            assert ls.transaction == "rent"
            assert ls.currency == "CZK"


class TestParseArea:
    def test_integer_area(self) -> None:
        assert _parse_area("Prodej bytu 2+kk 54 m²") == 54.0

    def test_decimal_area(self) -> None:
        assert _parse_area("Pronájem bytu 3+1 72,5 m²") == 72.5

    def test_no_area(self) -> None:
        assert _parse_area("Prodej bytu 2+kk") is None

    def test_m2_without_superscript(self) -> None:
        assert _parse_area("Prodej bytu 2+kk 54 m2") == 54.0

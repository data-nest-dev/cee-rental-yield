from __future__ import annotations

import json
from pathlib import Path

from src.config import CITIES
from src.sources.otodom import parse_otodom_items

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    data = json.loads((FIXTURE_DIR / name).read_text())
    return data["pageProps"]["data"]["searchAds"]["items"]


class TestOtodomRentParsing:
    def setup_method(self) -> None:
        self.raw = _load_fixture("otodom_rent_katowice.json")
        self.cfg = CITIES["katowice"]

    def test_parses_valid_listings(self) -> None:
        listings, rejected = parse_otodom_items(self.raw, self.cfg, "rent")
        assert len(listings) > 0
        for ls in listings:
            assert ls.source == "otodom"
            assert ls.transaction == "rent"
            assert ls.city == "Katowice"
            assert ls.price_local > 0
            assert ls.area_m2 > 0

    def test_rejects_hpr_ad_insert(self) -> None:
        """§6.1 trap 4: element id=9000062324 with href starting with hpr/"""
        listings, rejected = parse_otodom_items(self.raw, self.cfg, "rent")
        ids = {ls.listing_id for ls in listings}
        assert "9000062324" not in ids
        assert rejected.get("ad_insert", 0) >= 1

    def test_rejects_swapped_rent(self) -> None:
        """§6.1 trap 3: id=68642713 has totalPrice=600, rentPrice=1900"""
        listings, rejected = parse_otodom_items(self.raw, self.cfg, "rent")
        ids = {ls.listing_id for ls in listings}
        assert "68642713" not in ids
        assert rejected.get("swapped_rent", 0) >= 1

    def test_deduplicates_by_slug(self) -> None:
        """§6.1 trap 4: hpr/ item duplicates slug of real item"""
        listings, rejected = parse_otodom_items(self.raw, self.cfg, "rent")
        slugs = [ls.dedup_key for ls in listings]
        assert len(slugs) == len(set(slugs))

    def test_strips_pii(self) -> None:
        """PII fields should be removed during parsing"""
        listings, _ = parse_otodom_items(self.raw, self.cfg, "rent")
        # Verify that raw items had PII stripped
        for item in self.raw:
            assert "title" not in item
            assert "shortDescription" not in item
            assert "images" not in item

    def test_rooms_mapping(self) -> None:
        listings, _ = parse_otodom_items(self.raw, self.cfg, "rent")
        rooms_seen = {ls.rooms for ls in listings if ls.rooms is not None}
        assert rooms_seen.issubset({1, 2, 3, 4, 5, 6, 7, 8, 9, 10})

    def test_district_extracted(self) -> None:
        listings, _ = parse_otodom_items(self.raw, self.cfg, "rent")
        with_district = [ls for ls in listings if ls.district is not None]
        assert len(with_district) > 0

    def test_url_format(self) -> None:
        listings, _ = parse_otodom_items(self.raw, self.cfg, "rent")
        for ls in listings:
            assert ls.url.startswith("https://www.otodom.pl/pl/oferta/")


class TestOtodomSaleParsing:
    def setup_method(self) -> None:
        self.raw = _load_fixture("otodom_sale_katowice.json")
        self.cfg = CITIES["katowice"]

    def test_parses_sale_listings(self) -> None:
        listings, rejected = parse_otodom_items(self.raw, self.cfg, "sale")
        assert len(listings) > 0
        for ls in listings:
            assert ls.transaction == "sale"

    def test_transaction_is_sell(self) -> None:
        """Verify SELL transaction value in fixture"""
        for item in self.raw:
            if item.get("estate") == "FLAT" and not item.get("href", "").startswith("hpr/"):
                assert item.get("transaction") == "SELL"
                break

    def test_primary_market_labels_under_market_all(self) -> None:
        """market=ALL: developmentId > 0 -> True, otherwise unknown (None), never a false False."""
        listings, _ = parse_otodom_items(self.raw, self.cfg, "sale")
        assert {ls.is_primary_market for ls in listings} <= {True, None}
        raw_by_slug = {r["slug"]: r for r in self.raw if r.get("slug")}
        for ls in listings:
            dev = raw_by_slug[ls.dedup_key].get("developmentId") or 0
            assert (ls.is_primary_market is True) == (dev > 0)

    def test_primary_market_labels_under_market_secondary(self) -> None:
        """market=SECONDARY (portal filter): every listing is certainly not primary."""
        listings, _ = parse_otodom_items(self.raw, self.cfg, "sale", market="SECONDARY")
        assert listings
        assert {ls.is_primary_market for ls in listings} == {False}

    def test_rent_price_is_admin_fee_for_sale(self) -> None:
        """§6.1 trap 1: rentPrice in SALE listings is admin fee, not rent."""
        listings, _ = parse_otodom_items(self.raw, self.cfg, "sale")
        with_fee = [ls for ls in listings if ls.admin_fee_local is not None]
        # Admin fees should be much smaller than sale prices
        for ls in with_fee:
            assert ls.admin_fee_local < ls.price_local


class TestInvestmentTiles:
    def setup_method(self) -> None:
        self.raw = _load_fixture("otodom_sale_katowice.json")
        self.cfg = CITIES["katowice"]

    def test_investment_tiles_counted_separately(self) -> None:
        _, rejected = parse_otodom_items(self.raw, self.cfg, "sale")
        assert rejected.get("primary_market_project") == 8
        assert "not_flat" not in rejected

    def test_related_ads_and_owner_data_stripped(self) -> None:
        parse_otodom_items(self.raw, self.cfg, "sale")
        for item in self.raw:
            for key in ("relatedAds", "advertOwner", "agency", "organisationAssignedMember"):
                assert key not in item


def test_duplicate_investment_tiles_counted_once() -> None:
    raw = _load_fixture("otodom_sale_katowice.json")
    tiles = [dict(it) for it in raw if it.get("estate") == "INVESTMENT"]
    _, rejected = parse_otodom_items(raw + tiles + tiles, CITIES["katowice"], "sale")
    assert rejected["primary_market_project"] == 8
    assert rejected["duplicate"] == 16

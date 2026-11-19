from __future__ import annotations

import copy
import json
from pathlib import Path

from src.config import CITIES
from src.location import address_city_differs, names_other_city
from src.sources.otodom import parse_otodom_items

FIXTURES = Path(__file__).parent / "fixtures"


def _misplaced_listing() -> dict:
    """Location fields of the real case (Gdańsk flat filed under Warszawa / Żoliborz); everything else synthetic."""
    items = json.loads((FIXTURES / "otodom_sale_katowice.json").read_text())["pageProps"]["data"]["searchAds"]["items"]
    flat = next(copy.deepcopy(i) for i in items if i.get("estate") == "FLAT" and not i["href"].startswith("hpr/"))
    flat["slug"] = "mieszkanie-inwestycyjne-na-sprzedaz-oxygen-park-gdansk-ID4E1Q9"
    flat["title"] = "Mieszkanie inwestycyjne Oxygen Park Gdańsk"
    flat["location"] = {
        "mapDetails": {"radius": 7500},
        "address": {"street": None, "city": None, "province": None},
        "reverseGeocoding": {"locations": [
            {"id": "mazowieckie", "locationLevel": "voivodeship", "name": "mazowieckie"},
            {"id": "mazowieckie/warszawa/warszawa/warszawa", "locationLevel": "city_or_village", "name": "Warszawa"},
            {"id": "mazowieckie/warszawa/warszawa/warszawa/zoliborz", "locationLevel": "district", "name": "Żoliborz"},
        ]},
    }
    return flat


def test_listing_filed_under_warsaw_but_named_gdansk_is_outside_city() -> None:
    listings, rejected = parse_otodom_items([_misplaced_listing()], CITIES["warszawa"], "sale")
    assert listings == [] and rejected == {"outside_city": 1}


def test_same_listing_without_the_foreign_name_is_kept() -> None:
    flat = _misplaced_listing()
    flat["slug"], flat["title"] = "mieszkanie-zoliborz-ID1", "Mieszkanie Żoliborz"
    listings, _ = parse_otodom_items([flat], CITIES["warszawa"], "sale")
    assert len(listings) == 1


def test_title_alone_is_enough() -> None:
    flat = _misplaced_listing()
    flat["slug"] = "mieszkanie-2-pokoje-ID2"
    assert parse_otodom_items([flat], CITIES["warszawa"], "sale")[1] == {"outside_city": 1}


def test_street_names_and_both_cities_do_not_trigger() -> None:
    assert not names_other_city("warszawa", "mieszkanie-ul-gdanska-krakowskie-przedmiescie-warszawa")
    assert not names_other_city("warszawa", "mieszkanie-w-warszawie-blisko-gdansku")
    assert not names_other_city("krakow", "mieszkanie-krakow-podgorze-ID3")
    assert names_other_city("krakow", "Mieszkanie w Gdańsku")


def test_address_city_only_counts_when_it_names_another_known_city() -> None:
    assert address_city_differs("warszawa", "Gdańsk")
    assert not address_city_differs("warszawa", "Warszawa")
    assert not address_city_differs("warszawa", "Śródmieście")
    assert not address_city_differs("warszawa", None)

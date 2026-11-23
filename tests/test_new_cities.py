"""Łódź, Gdańsk and Poznań are configured like the other Otodom cities."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.config import CITIES
from src.sources.otodom import parse_otodom_items

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
NEW = {
    "lodz": ("Łódź", "lodzkie/lodz/lodz/lodz"),
    "gdansk": ("Gdańsk", "pomorskie/gdansk/gdansk/gdansk"),
    "poznan": ("Poznań", "wielkopolskie/poznan/poznan/poznan"),
}


@pytest.mark.parametrize("key", NEW)
def test_city_config(key: str) -> None:
    name, path = NEW[key]
    cfg = CITIES[key]
    assert (cfg.display_name, cfg.location_path, cfg.country, cfg.currency, cfg.source) == (
        name, path, "PL", "PLN", "otodom")
    assert len(path.split("/")) == 4 and path.endswith(f"/{key}")


def test_input_schema_enum_matches_config() -> None:
    items = json.loads((ROOT / ".actor/input_schema.json").read_text())["properties"]["cities"]["items"]
    assert set(items["enum"]) == set(CITIES)
    assert len(items["enumTitles"]) == len(items["enum"])
    assert dict(zip(items["enum"], items["enumTitles"]))["lodz"] == "Łódź"


def test_prefill_is_unchanged() -> None:
    props = json.loads((ROOT / ".actor/input_schema.json").read_text())["properties"]
    assert props["cities"]["prefill"] == ["warszawa"]


@pytest.mark.parametrize("key", NEW)
def test_parser_accepts_listing_in_new_city(key: str) -> None:
    name, path = NEW[key]
    raw = json.loads((FIXTURES / "otodom_sale_katowice.json").read_text())["pageProps"]["data"]["searchAds"]["items"]
    item = copy.deepcopy(next(i for i in raw if i.get("estate") == "FLAT" and i.get("totalPrice")))
    for loc in item["location"]["reverseGeocoding"]["locations"]:
        loc["id"] = loc["id"].replace("slaskie/katowice/katowice/katowice", path)
    listings, _ = parse_otodom_items([item], CITIES[key], "sale")
    assert len(listings) == 1 and listings[0].city == name and listings[0].district

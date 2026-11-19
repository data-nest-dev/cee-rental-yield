from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.config import CITIES
from src.flags import classify_title
from src.sources.otodom import parse_otodom_items

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("title,expected", [
    ("Udział w mieszkaniu 2 pokoje", {"share"}),
    ("1/2 udziału w mieszkaniu", {"share"}),
    ("Sprzedam udział, 2 pokoje", {"share"}),
    ("Udział w lokalu mieszkalnym", {"share"}),
    ("Udział 1/3 w nieruchomości", {"share"}),
    ("Udział w hali garażowej", set()),
    ("Udział w garażu podziemnym", set()),
    ("Udział w miejscu postojowym", set()),
    ("Sprzedam udział w gruncie", set()),
    ("Udział w działce, mieszkanie obok", set()),
    ("1/2 mieszkania w centrum", set()),
    ("LICYTACJA KOMORNICZA mieszkanie", {"auction"}),
    ("Mieszkanie do remontu, Bogucice", {"needsRenovation"}),
    ("Wymaga generalnego remontu", {"needsRenovation"}),
    ("Mieszkanie po remoncie, 2 pokoje", set()),
    ("Przestronne mieszkanie z balkonem", set()),
    (None, set()),
    ("", set()),
])
def test_classify_title(title, expected) -> None:
    assert classify_title(title) == expected


def _flat_with_title(title: str, slug: str) -> dict:
    items = json.loads((FIXTURES / "otodom_sale_katowice.json").read_text())["pageProps"]["data"]["searchAds"]["items"]
    flat = next(copy.deepcopy(i) for i in items if i.get("estate") == "FLAT" and not i["href"].startswith("hpr/"))
    flat["slug"], flat["title"] = slug, title
    return flat


def test_parser_excludes_share_and_auction_and_flags_renovation_without_keeping_title() -> None:
    raw = [
        _flat_with_title("Udział w mieszkaniu", "s1"),
        _flat_with_title("Licytacja komornicza", "s2"),
        _flat_with_title("Mieszkanie do remontu", "s3"),
        _flat_with_title("Zwykłe mieszkanie", "s4"),
    ]
    listings, rejected = parse_otodom_items(raw, CITIES["katowice"], "sale")
    assert rejected["share_listing"] == 1 and rejected["auction_listing"] == 1
    by_slug = {ls.dedup_key: ls for ls in listings}
    assert set(by_slug) == {"s3", "s4"}
    assert by_slug["s3"].flags == ("needsRenovation",)
    assert by_slug["s4"].flags == ()
    assert all("title" not in r for r in raw)
    assert "Mieszkanie do remontu" not in repr(listings)

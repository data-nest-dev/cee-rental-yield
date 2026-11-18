from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CityConfig:
    key: str
    display_name: str
    country: str
    currency: str
    source: str
    location_path: str  # otodom: slug segments; sreality: URL path segment


CITIES: dict[str, CityConfig] = {
    "katowice": CityConfig(
        key="katowice",
        display_name="Katowice",
        country="PL",
        currency="PLN",
        source="otodom",
        location_path="slaskie/katowice/katowice/katowice",
    ),
    "warszawa": CityConfig(
        key="warszawa",
        display_name="Warszawa",
        country="PL",
        currency="PLN",
        source="otodom",
        location_path="mazowieckie/warszawa/warszawa/warszawa",
    ),
    "krakow": CityConfig(
        key="krakow",
        display_name="Kraków",
        country="PL",
        currency="PLN",
        source="otodom",
        location_path="malopolskie/krakow/krakow/krakow",
    ),
    "wroclaw": CityConfig(
        key="wroclaw",
        display_name="Wrocław",
        country="PL",
        currency="PLN",
        source="otodom",
        location_path="dolnoslaskie/wroclaw/wroclaw/wroclaw",
    ),
    "praha": CityConfig(
        key="praha",
        display_name="Praha",
        country="CZ",
        currency="CZK",
        source="sreality",
        location_path="praha",
    ),
    "brno": CityConfig(
        key="brno",
        display_name="Brno",
        country="CZ",
        currency="CZK",
        source="sreality",
        location_path="brno",
    ),
    "ostrava": CityConfig(
        key="ostrava",
        display_name="Ostrava",
        country="CZ",
        currency="CZK",
        source="sreality",
        location_path="ostrava",
    ),
}

OTODOM_TRANSACTION_MAP = {"sale": "sprzedaz", "rent": "wynajem"}
SREALITY_TRANSACTION_MAP = {"sale": "prodej", "rent": "pronajem"}

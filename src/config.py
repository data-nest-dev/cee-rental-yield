from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CityConfig:
    key: str
    display_name: str
    country: str
    currency: str
    source: str
    location_path: str  # otodom: 4-segment slug


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
    "lodz": CityConfig(
        key="lodz",
        display_name="Łódź",
        country="PL",
        currency="PLN",
        source="otodom",
        location_path="lodzkie/lodz/lodz/lodz",
    ),
    "gdansk": CityConfig(
        key="gdansk",
        display_name="Gdańsk",
        country="PL",
        currency="PLN",
        source="otodom",
        location_path="pomorskie/gdansk/gdansk/gdansk",
    ),
    "poznan": CityConfig(
        key="poznan",
        display_name="Poznań",
        country="PL",
        currency="PLN",
        source="otodom",
        location_path="wielkopolskie/poznan/poznan/poznan",
    ),
}

OTODOM_TRANSACTION_MAP = {"sale": "sprzedaz", "rent": "wynajem"}

# Per-district quota per market side when maxListingsPerDistrict = 0 (owner decision 2026-11-18,
# CLAUDE.md §0 decision 5): at least 150, more in cities with few districts (Wrocław: 5 -> 300).
AUTO_QUOTA_MIN = 150
AUTO_QUOTA_CITY_TARGET = 1500


def auto_district_quota(n_districts: int) -> int:
    return max(AUTO_QUOTA_MIN, math.ceil(AUTO_QUOTA_CITY_TARGET / max(n_districts, 1)))


# Portal-side market filter (Otodom pageProps.filteringQueryParams.market). No field on a listing
# tells the markets apart reliably (CLAUDE.md section 6.1), so SECONDARY is applied by the portal.
MARKET_ALL = "ALL"
MARKET_SECONDARY = "SECONDARY"

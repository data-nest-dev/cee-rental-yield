from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.config import CITIES, MARKET_ALL, MARKET_SECONDARY

MODES = ("yieldReport", "scoreListings", "both")
SAMPLING_MODES = ("perDistrict", "city")
ROOM_BUCKETS = ("1", "2", "3", "4+")
STATE_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")

DEFAULT_PROXY = {"useApifyProxy": True, "apifyProxyGroups": ["BUYPROXIES94952"]}
# Same values as `prefill` in .actor/input_schema.json (Apify's daily test input); a test keeps them in sync.
PREFILL_INPUT = {
    "cities": ["warszawa"],
    "samplingMode": "city",
    "maxListingsPerSide": 360,
    "proxyConfiguration": DEFAULT_PROXY,
}


class InputError(ValueError):
    pass


@dataclass
class RunInput:
    cities: list[str] = field(default_factory=lambda: ["warszawa", "krakow"])
    mode: str = "both"
    rooms: tuple[str, ...] = ROOM_BUCKETS
    area_min: int = 15
    area_max: int = 250
    sampling_mode: str = "perDistrict"
    max_listings_per_district: int = 0  # 0 = automatic, see config.auto_district_quota
    max_listings_per_side: int = 1500
    min_score: int = 0
    max_scored_listings: int = 1000  # 0 = all
    include_primary_market: bool = True
    min_sale_sample: int = 15
    min_rent_sample: int = 10
    only_new_or_changed: bool = False
    state_key: str = "default"
    proxy_configuration: dict | None = field(default_factory=lambda: dict(DEFAULT_PROXY))

    @property
    def wants_yields(self) -> bool:
        return self.mode in ("yieldReport", "both")

    @property
    def wants_scores(self) -> bool:
        return self.mode in ("scoreListings", "both")

    @property
    def market(self) -> str:
        """Portal market filter: ALL, or SECONDARY when new builds are excluded."""
        return MARKET_ALL if self.include_primary_market else MARKET_SECONDARY

    def max_per_district_arg(self) -> int | None:
        """Argument for OtodomSource.fetch_listings: None = city-wide, 0 = automatic quota."""
        return self.max_listings_per_district if self.sampling_mode == "perDistrict" else None


def parse_input(raw: dict | None) -> RunInput:
    raw = raw or {}
    d = RunInput()

    cities = raw.get("cities", d.cities)
    if not isinstance(cities, list) or not cities:
        raise InputError("Input 'cities' must be a non-empty list.")
    unknown = [c for c in cities if c not in CITIES]
    if unknown:
        raise InputError(f"Unknown cities: {', '.join(map(str, unknown))}. Supported: {', '.join(CITIES)}.")
    cities = list(dict.fromkeys(cities))

    rooms = raw.get("rooms", list(d.rooms))
    if not isinstance(rooms, list) or not rooms:
        raise InputError("Input 'rooms' must be a non-empty list.")
    buckets = []
    for r in rooms:
        # Integers are accepted for API callers: 4 means "4 or more".
        b = "4+" if r in (4, "4") else str(r)
        if b not in ROOM_BUCKETS:
            raise InputError(f"Invalid room value {r!r}. Use {', '.join(ROOM_BUCKETS)}.")
        buckets.append(b)

    result = RunInput(
        cities=cities,
        mode=_enum(raw, "mode", d.mode, MODES),
        rooms=tuple(b for b in ROOM_BUCKETS if b in buckets),
        area_min=_int(raw, "areaMin", d.area_min, 1, 1000),
        area_max=_int(raw, "areaMax", d.area_max, 1, 1000),
        sampling_mode=_enum(raw, "samplingMode", d.sampling_mode, SAMPLING_MODES),
        max_listings_per_district=_int(raw, "maxListingsPerDistrict", d.max_listings_per_district, 0, 10000),
        max_listings_per_side=_int(raw, "maxListingsPerSide", d.max_listings_per_side, 1, 20000),
        min_score=_int(raw, "minScore", d.min_score, 0, 100),
        max_scored_listings=_int(raw, "maxScoredListings", d.max_scored_listings, 0, 1_000_000),
        include_primary_market=_bool(raw, "includePrimaryMarket", d.include_primary_market),
        min_sale_sample=_int(raw, "minSaleSample", d.min_sale_sample, 1, 10000),
        min_rent_sample=_int(raw, "minRentSample", d.min_rent_sample, 1, 10000),
        only_new_or_changed=_bool(raw, "onlyNewOrChanged", d.only_new_or_changed),
        state_key=raw.get("stateKey", d.state_key),
        proxy_configuration=raw.get("proxyConfiguration", d.proxy_configuration),
    )
    if result.area_min >= result.area_max:
        raise InputError("Input 'areaMin' must be smaller than 'areaMax'.")
    if not isinstance(result.state_key, str) or not STATE_KEY_RE.match(result.state_key):
        raise InputError("Input 'stateKey' may contain only letters, digits, '.', '_' and '-' (max 100).")
    if result.proxy_configuration is not None and not isinstance(result.proxy_configuration, dict):
        raise InputError("Input 'proxyConfiguration' must be an object.")
    return result


def is_prefill_run(run_input: RunInput) -> bool:
    return run_input == parse_input(PREFILL_INPUT)


def _enum(raw: dict, key: str, default: str, allowed: tuple[str, ...]) -> str:
    value = raw.get(key, default)
    if value not in allowed:
        raise InputError(f"Input '{key}' must be one of: {', '.join(allowed)}.")
    return value


def _int(raw: dict, key: str, default: int, lo: int, hi: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise InputError(f"Input '{key}' must be an integer between {lo} and {hi}.")
    return value


def _bool(raw: dict, key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise InputError(f"Input '{key}' must be true or false.")
    return value

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import auto_district_quota
from src.inputs import PREFILL_INPUT, InputError, RunInput, is_prefill_run, parse_input

SCHEMA = json.loads((Path(__file__).parent.parent / ".actor" / "input_schema.json").read_text())["properties"]


def test_empty_input_gives_defaults() -> None:
    r = parse_input({})
    assert r == RunInput()
    assert r.cities == ["warszawa", "krakow"]
    assert r.sampling_mode == "perDistrict"
    assert r.max_per_district_arg() == 0  # automatic quota
    assert r.wants_yields and r.wants_scores


def test_city_mode_disables_per_district_quota() -> None:
    r = parse_input({"samplingMode": "city", "maxListingsPerSide": 360})
    assert r.max_per_district_arg() is None
    assert r.max_listings_per_side == 360


def test_rooms_accept_strings_and_integers_and_dedupe_cities() -> None:
    r = parse_input({"rooms": [4, "2", "4+"], "cities": ["krakow", "krakow"]})
    assert r.rooms == ("2", "4+")
    assert r.cities == ["krakow"]


@pytest.mark.parametrize("raw, fragment", [
    ({"cities": []}, "non-empty"),
    ({"cities": ["praha"]}, "Unknown cities: praha"),
    ({"mode": "all"}, "'mode' must be one of"),
    ({"rooms": ["5"]}, "Invalid room value"),
    ({"areaMin": 100, "areaMax": 50}, "smaller than"),
    ({"minScore": 101}, "between 0 and 100"),
    ({"maxListingsPerSide": True}, "integer"),
    ({"stateKey": "a/b"}, "stateKey"),
    ({"onlyNewOrChanged": "yes"}, "true or false"),
    ({"proxyConfiguration": "x"}, "must be an object"),
])
def test_invalid_input_raises_readable_error(raw: dict, fragment: str) -> None:
    with pytest.raises(InputError, match=fragment):
        parse_input(raw)


def test_schema_defaults_match_run_input_defaults() -> None:
    d = parse_input({})
    expected = {
        "cities": d.cities, "mode": d.mode, "rooms": list(d.rooms), "areaMin": d.area_min,
        "areaMax": d.area_max, "samplingMode": d.sampling_mode,
        "maxListingsPerDistrict": d.max_listings_per_district, "maxListingsPerSide": d.max_listings_per_side,
        "minScore": d.min_score, "maxScoredListings": d.max_scored_listings,
        "includePrimaryMarket": d.include_primary_market,
        "minSaleSample": d.min_sale_sample, "minRentSample": d.min_rent_sample,
        "onlyNewOrChanged": d.only_new_or_changed, "stateKey": d.state_key,
        "proxyConfiguration": d.proxy_configuration,
    }
    assert set(SCHEMA) == set(expected)
    for key, value in expected.items():
        assert SCHEMA[key]["default"] == value, key


def test_prefill_is_a_valid_small_run() -> None:
    prefill = {k: v["prefill"] for k, v in SCHEMA.items() if "prefill" in v}
    r = parse_input(prefill)
    assert r.cities == ["warszawa"]
    assert r.sampling_mode == "city" and r.max_listings_per_side == 360
    assert prefill == PREFILL_INPUT
    assert is_prefill_run(r) and not is_prefill_run(parse_input({}))


def test_max_scored_listings_bounds() -> None:
    assert parse_input({"maxScoredListings": 0}).max_scored_listings == 0
    with pytest.raises(InputError, match="maxScoredListings"):
        parse_input({"maxScoredListings": -1})


@pytest.mark.parametrize("n, quota", [(18, 150), (22, 150), (5, 300), (10, 150), (7, 215), (1, 1500), (0, 1500)])
def test_auto_district_quota(n: int, quota: int) -> None:
    assert auto_district_quota(n) == quota


def test_console_prefill_json_is_recognised_as_prefill_run() -> None:
    """Exact input the Apify Console sends for the prefill (no `mode`, explicit defaults)."""
    console = {
        "cities": ["warszawa"], "includePrimaryMarket": True, "maxListingsPerSide": 360,
        "onlyNewOrChanged": False,
        "proxyConfiguration": {"useApifyProxy": True},
        "samplingMode": "city",
    }
    assert is_prefill_run(parse_input(console))
    assert not is_prefill_run(parse_input({}))

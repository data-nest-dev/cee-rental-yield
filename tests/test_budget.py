from __future__ import annotations

import pytest

from src.budget import (
    estimate_author_cost_usd, estimate_records, estimate_requests, min_max_charge_usd, needs_budget_mode, reduced_input,
)
from src.inputs import parse_input

DEFAULT = parse_input({})
PREFILL = parse_input({"cities": ["warszawa"], "samplingMode": "city", "maxListingsPerSide": 360})
RESIDENTIAL = {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"], "apifyProxyCountry": "PL"}


def test_request_estimates() -> None:
    assert estimate_requests(DEFAULT) == 2 * 2 * 60
    assert estimate_requests(PREFILL) == 1 * 2 * (9 + 1)       # ceil(1.7 * 360 / 72) = 9
    assert estimate_requests(parse_input({"samplingMode": "city"})) == 2 * 2 * (36 + 1)


def test_records_estimate() -> None:
    assert estimate_records(DEFAULT) == 110 + 1000
    assert estimate_records(PREFILL) == 55 + 324                      # 0.9 x 360 listings, all scored
    assert estimate_records(parse_input({"maxScoredListings": 0})) == 110 + 6000
    assert estimate_records(parse_input({"mode": "yieldReport"})) == 110


def test_run_2_estimate_matches_measured_cost() -> None:
    # Run 2 (256 MB): compute 0.0055 + 1110 records 0.0060 + 20 KV writes 0.0010; measured $0.012
    assert estimate_author_cost_usd(DEFAULT, 256) == pytest.approx(0.0125, abs=3e-4)
    assert estimate_author_cost_usd(DEFAULT, 256) >= 0.012          # never below the measured cost


def test_default_and_prefill_thresholds_on_datacenter_proxy() -> None:
    assert estimate_author_cost_usd(DEFAULT, 512) == pytest.approx(0.0162, abs=3e-4)
    assert min_max_charge_usd(DEFAULT, 512) == pytest.approx(0.0304, abs=5e-4)
    assert min_max_charge_usd(DEFAULT, 256) == pytest.approx(0.0235, abs=5e-4)
    assert min_max_charge_usd(PREFILL, 512) == pytest.approx(0.0087, abs=3e-4)


def test_residential_proxy_adds_traffic_cost() -> None:
    res = parse_input({"proxyConfiguration": RESIDENTIAL})
    # 240 requests x 0.46 MB x $8/GB = $0.883 on top of compute and storage
    assert estimate_author_cost_usd(res, 512) == pytest.approx(0.0162 + 0.8832, abs=2e-3)
    assert min_max_charge_usd(res, 512) == pytest.approx(1.686, abs=0.01)


@pytest.mark.parametrize("ppe, max_charge, cost, expected", [
    (True, 0.01, 0.0157, True),     # 0.008 < 0.0235
    (True, 0.03, 0.0157, False),    # 0.024 >= 0.0235
    (True, None, 0.0157, False),    # no limit
    (False, 0.01, 0.0157, False),   # not pay-per-event (owner's own runs)
])
def test_needs_budget_mode(ppe: bool, max_charge, cost: float, expected: bool) -> None:
    assert needs_budget_mode(ppe, max_charge, cost) is expected


def test_reduced_input_matches_prefill_scope() -> None:
    r = reduced_input(parse_input({"cities": ["krakow", "warszawa"], "mode": "scoreListings", "rooms": ["2"]}))
    # mode is kept: budget mode never makes the user pay for an event type they did not ask for
    assert (r.cities, r.sampling_mode, r.max_listings_per_side, r.mode) == (["krakow"], "city", 360, "scoreListings")
    assert r.rooms == ("2",)

from __future__ import annotations

import math
from dataclasses import replace

from src.inputs import RunInput

# Author's platform cost model (under pay-per-event the author pays compute, proxy and transfer).
# Measured 2026-11-18, LATEST/72, home IP, no proxy (CLAUDE.md §6.1 "Pomiar decyzyjny"):
SECONDS_PER_REQUEST = 1.05             # Warszawa + Kraków per-district default: 214 requests in ~220 s
FIXED_SECONDS = 30                     # start, ECB rate, stats and push; estimate, calibrate in test H
REQUESTS_PER_SIDE_PER_DISTRICT = 60    # per-district automatic quota: 25-80 per side measured, mean 48
CITY_MODE_REQUEST_FACTOR = 1.7         # whole-city mode: ceil(1.7 * listings / 72) + 1 per side (measured 21-35 at 1500)
PAGE_SIZE = 72
BYTES_PER_REQUEST = 460_000            # decompressed JSON page, 0.40-0.53 MB measured; upper bound for proxy traffic
# Prices:
USD_PER_COMPUTE_UNIT = 0.40            # ASSUMPTION (plan-dependent, not in the docs); replace after test H billing
RESIDENTIAL_USD_PER_GB = 8.0           # owner's account; datacenter group is included in the plan
DEFAULT_MEMORY_MB = 512                # .actor/actor.json defaultMemoryMbytes
# Rule (owner decision 2026-11-18): reduce when 0.8 x max charge < estimated cost x 1.5.
AUTHOR_SHARE = 0.8                     # Apify keeps 20% of PPE revenue
SAFETY_FACTOR = 1.5
# Reduced scope, same as the input schema prefill (Apify's daily test input).
BUDGET_CITIES = 1
BUDGET_LISTINGS_PER_SIDE = 360

BUDGET_WARNING = (
    "Max charge too low for the requested scope; "
    f"running a reduced sample ({BUDGET_CITIES} city, {BUDGET_LISTINGS_PER_SIDE} listings per side)."
)


def estimate_requests(run_input: RunInput) -> int:
    if run_input.sampling_mode == "perDistrict":
        per_side = REQUESTS_PER_SIDE_PER_DISTRICT
    else:
        per_side = math.ceil(CITY_MODE_REQUEST_FACTOR * run_input.max_listings_per_side / PAGE_SIZE) + 1
    return len(run_input.cities) * 2 * per_side


def uses_residential_proxy(run_input: RunInput) -> bool:
    proxy = run_input.proxy_configuration or {}
    return bool(proxy.get("useApifyProxy")) and "RESIDENTIAL" in (proxy.get("apifyProxyGroups") or [])


def estimate_author_cost_usd(run_input: RunInput, memory_mb: int | None = None) -> float:
    requests = estimate_requests(run_input)
    seconds = FIXED_SECONDS + requests * SECONDS_PER_REQUEST
    compute = (memory_mb or DEFAULT_MEMORY_MB) / 1024 * seconds / 3600 * USD_PER_COMPUTE_UNIT
    proxy = requests * BYTES_PER_REQUEST / 1e9 * RESIDENTIAL_USD_PER_GB if uses_residential_proxy(run_input) else 0.0
    return compute + proxy


def min_max_charge_usd(run_input: RunInput, memory_mb: int | None = None) -> float:
    """Smallest max charge that runs the requested scope unreduced."""
    return estimate_author_cost_usd(run_input, memory_mb) * SAFETY_FACTOR / AUTHOR_SHARE


def needs_budget_mode(is_pay_per_event: bool, max_charge_usd: float | None, estimated_cost_usd: float) -> bool:
    if not is_pay_per_event or max_charge_usd is None:
        return False
    return AUTHOR_SHARE * max_charge_usd < estimated_cost_usd * SAFETY_FACTOR


def reduced_input(run_input: RunInput) -> RunInput:
    # mode is kept: the user never pays for an event type they did not ask for. The pipeline adds only
    # free low-confidence yield records in budget mode so the dataset stays non-empty.
    return replace(
        run_input,
        cities=run_input.cities[:BUDGET_CITIES],
        sampling_mode="city",
        max_listings_per_side=BUDGET_LISTINGS_PER_SIDE,
    )

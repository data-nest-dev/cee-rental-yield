from __future__ import annotations

import math
from dataclasses import replace

from src.inputs import RunInput

# Author's platform cost model (under pay-per-event the author pays compute, proxy and transfer).
# Calibrated on test H (2026-11-19, platform, datacenter proxy): run 1 at 512 MB and run 2 at 256 MB.
# Run 2 cost breakdown from the Console: compute 0.0238 CU = $0.005, 1109 dataset writes = $0.006,
# 20 key-value writes = $0.001, transfer and proxy $0.
SECONDS_PER_REQUEST_512 = 1.19         # run 1: 255 s of fetch time / 215 requests at 512 MB
SECONDS_PER_REQUEST_256 = 1.45         # run 2: 1.45 s per request at 256 MB (slower CPU share)
FIXED_SECONDS = 30                     # start, ECB rate, stats and push; deliberately above the 12-22 s measured
REQUESTS_PER_SIDE_PER_DISTRICT = 60    # per-district automatic quota: 25-80 per side measured, mean 54
CITY_MODE_REQUEST_FACTOR = 1.7         # whole-city mode: ceil(1.7 * listings / 72) + 1 per side (measured 21-35 at 1500)
PAGE_SIZE = 72
BYTES_PER_REQUEST = 460_000            # decompressed JSON page, 0.40-0.53 MB measured; upper bound for proxy traffic
# Records the run writes (estimates for the default scope: 109 yield groups and 1000 scored listings for 2 cities)
GROUPS_PER_CITY = 55
AVAILABLE_SCORED_PER_CITY = 3000       # per-district default: about 3000 cleaned sales per city (2951-3140 measured)
CITY_MODE_YIELD = 0.9                  # share of listings per side that survives cleaning
KV_WRITES = 20                         # RUN_SUMMARY, YIELD_REPORT, state and status writes per run (run 2: 20)
# Prices:
USD_PER_COMPUTE_UNIT = 0.21            # run 2: $0.005 / 0.0238 CU (plan-dependent; Apify's list price is $0.20)
USD_PER_DATASET_WRITE = 0.006 / 1109   # run 2
USD_PER_KV_WRITE = 0.001 / 20          # run 2
RESIDENTIAL_USD_PER_GB = 8.0           # owner's account; datacenter group is included in the plan
DEFAULT_MEMORY_MB = 512                # .actor/actor.json defaultMemoryMbytes (owner decision 2026-11-19)
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


def seconds_per_request(memory_mb: int) -> float:
    return SECONDS_PER_REQUEST_512 if memory_mb >= 512 else SECONDS_PER_REQUEST_256


def estimate_records(run_input: RunInput) -> int:
    cities = len(run_input.cities)
    if run_input.sampling_mode == "perDistrict":
        available = AVAILABLE_SCORED_PER_CITY * cities
    else:
        available = int(CITY_MODE_YIELD * run_input.max_listings_per_side) * cities
    scored = min(run_input.max_scored_listings or available, available) if run_input.wants_scores else 0
    groups = GROUPS_PER_CITY * cities if run_input.wants_yields else 0
    return groups + scored


def estimate_author_cost_usd(run_input: RunInput, memory_mb: int | None = None) -> float:
    memory_mb = memory_mb or DEFAULT_MEMORY_MB
    requests = estimate_requests(run_input)
    seconds = FIXED_SECONDS + requests * seconds_per_request(memory_mb)
    compute_units = memory_mb / 1024 * seconds / 3600
    storage = estimate_records(run_input) * USD_PER_DATASET_WRITE + KV_WRITES * USD_PER_KV_WRITE
    proxy = requests * BYTES_PER_REQUEST / 1e9 * RESIDENTIAL_USD_PER_GB if uses_residential_proxy(run_input) else 0.0
    return compute_units * USD_PER_COMPUTE_UNIT + storage + proxy


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

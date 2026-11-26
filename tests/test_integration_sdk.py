"""Integration with the real Apify SDK (local storage, platform-like PPE prices from env); no network."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

HARNESS = Path(__file__).parent / "sdk_harness.py"
# Platform prices; apify-default-dataset-item is listed at $0 to emulate "removed in Console"
# (locally the SDK prices any unlisted event at $1, on the platform at $0).
PRICES = {"area-yield": 0.02, "scored-listing": 0.001, "apify-actor-start": 0.00005, "apify-default-dataset-item": 0}


def _run(tmp_path: Path, scenario: dict, max_usd: str) -> tuple[subprocess.CompletedProcess, Path]:
    pricing = {
        "pricingModel": "PAY_PER_EVENT", "apifyMarginPercentage": 0.2,
        "createdAt": "2026-11-01T00:00:00Z", "startedAt": "2026-11-01T00:00:00Z",
        "pricingPerEvent": {"actorChargeEvents": {
            name: {"eventPriceUsd": price, "eventTitle": name, "eventDescription": name} for name, price in PRICES.items()
        }},
    }
    env = {k: v for k, v in os.environ.items() if not k.startswith(("APIFY_", "ACTOR_", "CRAWLEE_"))}
    env.update(APIFY_ACTOR_PRICING_INFO=json.dumps(pricing),
               APIFY_CHARGED_ACTOR_EVENT_COUNTS=json.dumps({"apify-actor-start": 1}),
               ACTOR_MAX_TOTAL_CHARGE_USD=max_usd)
    proc = subprocess.run([sys.executable, str(HARNESS), json.dumps(scenario)], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=120)
    return proc, tmp_path / "storage"


def _dataset(storage: Path, alias: str = "default") -> list[dict]:
    files = sorted(p for p in (storage / "datasets" / alias).glob("*.json") if "__metadata__" not in p.name)
    return [json.loads(p.read_text()) for p in files]  # file order = push order


def _kv(storage: Path, store: str, key: str) -> dict:
    return json.loads((storage / "key_value_stores" / store / key).read_text())


def _charged(summary: dict) -> Decimal:
    ev = summary["events"]
    return (Decimal("0.00005") + Decimal("0.02") * ev["area-yield"]["charged"]
            + Decimal("0.001") * ev["scored-listing"]["charged"])


def test_limit_mid_way_orders_yields_then_best_deals_and_stays_below_limit(tmp_path: Path) -> None:
    # $0.10: 4 charged groups ($0.08) fit, then 4 scored listings ($0.016); total 0.09605 < 0.10
    proc, storage = _run(tmp_path, {"input": {"cities": ["katowice"]}, "replicate": 8}, "0.10")
    assert proc.returncode == 0, proc.stderr[-2000:]
    summary = _kv(storage, "default", "RUN_SUMMARY")
    items = _dataset(storage)                    # default dataset: scored listings only
    yields = _dataset(storage, "yields")         # areaYield records live in the extra dataset

    assert summary["chargeLimitReached"] is True and summary["budgetReduced"] is False
    assert summary["yieldsDataset"] == "yields"
    assert items and all(i["recordType"] == "scoredListing" for i in items)
    assert yields and all(i["recordType"] == "areaYield" for i in yields)
    assert yields[0]["confidence"] == "low"                                   # free context first
    scores = [i["dealScore"] for i in items]
    assert len(scores) == 19 and scores == sorted(scores, reverse=True)       # best deals first
    assert summary["events"]["area-yield"]["charged"] == 4                    # Actor.charge on the aliased dataset
    assert _charged(summary) == Decimal("0.09905") < Decimal("0.10")
    report = _kv(storage, "default", "YIELD_REPORT")
    reported = [g for c in report["cities"].values() for g in c["groups"]]
    assert len(reported) == len(yields)                                       # only delivered groups


def test_listings_held_back_by_the_limit_are_not_marked_seen(tmp_path: Path) -> None:
    scenario = {"input": {"cities": ["katowice"], "mode": "scoreListings", "onlyNewOrChanged": True,
                          "watchlistName": "watch-1"}, "replicate": 8}
    proc, storage = _run(tmp_path, scenario, "0.01")
    assert proc.returncode == 0, proc.stderr[-2000:]
    summary = _kv(storage, "default", "RUN_SUMMARY")
    state = _kv(storage, "cee-rental-yield-state", "watch-1")
    delivered = [i for i in _dataset(storage) if i["recordType"] == "scoredListing"]  # monitoring test; default dataset
    assert summary["budgetReduced"] is True and len(delivered) == 9
    assert len(state) == 9                                     # only the delivered listings are now "seen"
    assert summary["monitoring"]["heldBack"] == summary["scoredAvailable"] - 9


def test_one_cent_limit_succeeds_with_free_context_and_nine_listings(tmp_path: Path) -> None:
    proc, storage = _run(tmp_path, {"input": {"cities": ["warszawa", "krakow"]}}, "0.01")
    assert proc.returncode == 0, proc.stderr[-2000:]
    summary = _kv(storage, "default", "RUN_SUMMARY")
    items = _dataset(storage)
    yields = _dataset(storage, "yields")
    assert summary["budgetReduced"] is True
    assert [i["recordType"] for i in items] == ["scoredListing"] * 9
    assert yields and all(i["confidence"] == "low" for i in yields)
    assert _charged(summary) == Decimal("0.00905")


def test_yield_report_copy_to_yields_dataset_is_not_charged(tmp_path: Path) -> None:
    # mode yieldReport: yields stay in the default dataset (API) and are copied to `yields` for the Output view.
    proc, storage = _run(tmp_path, {"input": {"cities": ["katowice"], "mode": "yieldReport"}, "replicate": 8}, "5")
    assert proc.returncode == 0, proc.stderr[-2000:]
    summary = _kv(storage, "default", "RUN_SUMMARY")
    default, copy = _dataset(storage), _dataset(storage, "yields")
    assert default and all(r["recordType"] == "areaYield" for r in default)
    assert copy == default and summary["yieldsDataset"] == "default"
    ev = summary["events"]
    assert ev["area-yield"]["charged"] == ev["area-yield"]["chargeable"] > 0 and ev["scored-listing"]["charged"] == 0
    assert _charged(summary) == Decimal("0.00005") + Decimal("0.02") * ev["area-yield"]["charged"]  # copy adds no charge

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from src.charging import push_with_charging
from src.fx import parse_ecb_rates
from src.http import BlockedError, HttpClient
from src.pipeline import run

FIXTURES = Path(__file__).parent / "fixtures"
ITEMS = {
    tx: json.loads((FIXTURES / f"otodom_{tx}_katowice.json").read_text())["pageProps"]["data"]["searchAds"]["items"]
    for tx in ("sale", "rent")
}
AS_OF = date(2026, 11, 18)


class FakeActor:
    def __init__(self, capacity: dict[str, int] | None = None) -> None:
        self.pushed: list[tuple[str | None, list[dict]]] = []
        self.kv: dict[str, dict] = {}
        self.failed: str | None = None
        self.statuses: list[str] = []
        self.capacity = capacity  # remaining chargeable count per event; None = unlimited

    async def push(self, records: list[dict], event: str | None) -> tuple[int, bool]:
        async def pusher(batch: list[dict], charged_event: str | None) -> int:
            self.pushed.append((charged_event, list(batch)))
            if charged_event is not None and self.capacity is not None:
                self.capacity[charged_event] -= len(batch)
            return len(batch)
        return await push_with_charging(
            pusher, records, event,
            is_pay_per_event=self.capacity is not None,
            capacity=lambda e: None if self.capacity is None else self.capacity.get(e),
        )

    def charged_count(self, event: str) -> int | None:
        return None

    async def set_value(self, key: str, value: dict) -> None:
        self.kv[key] = copy.deepcopy(value)

    async def fail(self, message: str) -> None:
        self.failed = message

    async def status(self, message: str) -> None:
        self.statuses.append(message)

    def records(self, record_type: str) -> list[dict]:
        return [r for _, batch in self.pushed for r in batch if r["recordType"] == record_type]


class FakeSource:
    def __init__(self, blocked: set[str] = frozenset(), empty: set[str] = frozenset()) -> None:
        self.blocked = blocked
        self.empty = empty
        self.calls: list[tuple[str, str, int, int | None]] = []

    async def fetch_listings(self, city_key, transaction, max_listings, max_per_district=None):
        self.calls.append((city_key, transaction, max_listings, max_per_district))
        if city_key in self.blocked:
            raise BlockedError(f"www.otodom.pl blocked 9 of 11 requests ({city_key} {transaction})")
        items = [] if city_key in self.empty else copy.deepcopy(ITEMS[transaction])
        # The fixtures are Katowice listings; re-home them so any configured city accepts them.
        from src.config import CITIES
        target = CITIES[city_key].location_path
        for it in items:
            for loc in it.get("location", {}).get("reverseGeocoding", {}).get("locations", []):
                loc["id"] = loc.get("id", "").replace("slaskie/katowice/katowice/katowice", target)
        stats = {"pages_fetched": 1, "raw_items": len(items), "fetched_items": len(items),
                 "total_items": len(items) * 10, "build_id_refreshes": 0, "fallback_to_html": False}
        return items, stats


async def _rates(http: HttpClient):
    return parse_ecb_rates((FIXTURES / "ecb_daily.xml").read_text())


async def _broken_rates(http: HttpClient):
    raise RuntimeError("ECB rates returned HTTP 503")


async def _http(run_input) -> HttpClient:
    return HttpClient()


async def _run(raw_input: dict, source: FakeSource | None = None, actor: FakeActor | None = None, rates=_rates):
    actor = actor or FakeActor()
    source = source or FakeSource()
    summary = await run(actor, raw_input, http_factory=_http, source_factory=lambda http: source,
                        rates_loader=rates, as_of=AS_OF)
    return actor, source, summary


@pytest.mark.asyncio
async def test_successful_run_pushes_yields_and_scored_listings_sorted_by_score() -> None:
    actor, source, summary = await _run({"cities": ["katowice"]})

    assert actor.failed is None
    assert summary["status"] == "ok"
    assert summary["cities"]["katowice"]["status"] == "ok"
    assert set(summary["cities"]["katowice"]["sides"]) == {"sale", "rent"}
    area, scored = actor.records("areaYield"), actor.records("scoredListing")
    assert area and scored
    scores = [r["dealScore"] for r in scored]
    assert scores == sorted(scores, reverse=True)
    assert "YIELD_REPORT" in actor.kv and actor.kv["RUN_SUMMARY"]["status"] == "ok"
    assert all(r["sample"] is not None for r in area)
    # default input: per-district sampling with automatic quota
    assert source.calls[0] == ("katowice", "sale", 1500, 0)


@pytest.mark.asyncio
async def test_blocked_city_is_skipped_and_others_continue() -> None:
    actor, _, summary = await _run({"cities": ["warszawa", "katowice"]}, FakeSource(blocked={"warszawa"}))

    assert actor.failed is None
    assert summary["status"] == "partial"
    assert summary["cities"]["warszawa"]["status"] == "failed"
    assert "blocked" in summary["cities"]["warszawa"]["reason"]
    assert summary["cities"]["katowice"]["status"] == "ok"
    assert {r["city"] for r in actor.records("scoredListing")} == {"Katowice"}


@pytest.mark.asyncio
async def test_all_cities_failing_fails_the_run_without_pushing() -> None:
    actor, _, summary = await _run({"cities": ["warszawa", "krakow"]},
                                   FakeSource(blocked={"warszawa"}, empty={"krakow"}))

    assert actor.failed and "nothing was charged" in actor.failed
    assert actor.pushed == []
    assert summary["status"] == "failed"
    assert "no listings for sale" in summary["cities"]["krakow"]["reason"]
    assert actor.kv["RUN_SUMMARY"]["status"] == "failed"


@pytest.mark.asyncio
async def test_invalid_input_fails_before_fetching() -> None:
    actor, source, summary = await _run({"cities": ["praha"]})
    assert actor.failed and actor.failed.startswith("Invalid input")
    assert source.calls == [] and actor.pushed == []


@pytest.mark.asyncio
async def test_missing_ecb_rates_fail_without_pushing() -> None:
    actor, source, summary = await _run({"cities": ["katowice"]}, rates=_broken_rates)
    assert actor.failed and "ECB" in actor.failed
    assert source.calls == [] and actor.pushed == []


@pytest.mark.asyncio
async def test_filters_mode_rooms_and_min_score() -> None:
    actor, _, _ = await _run({"cities": ["katowice"], "mode": "scoreListings", "rooms": ["2"], "minScore": 60})
    scored = actor.records("scoredListing")
    assert actor.records("areaYield") == []
    assert "YIELD_REPORT" not in actor.kv
    assert scored and all(r["rooms"] == 2 and r["dealScore"] >= 60 for r in scored)


@pytest.mark.asyncio
async def test_yield_report_mode_pushes_no_scored_listings() -> None:
    actor, _, _ = await _run({"cities": ["katowice"], "mode": "yieldReport"})
    assert actor.records("scoredListing") == []
    assert actor.records("areaYield")


@pytest.mark.asyncio
async def test_city_mode_passes_side_limit_and_no_district_quota() -> None:
    _, source, _ = await _run({"cities": ["katowice"], "samplingMode": "city", "maxListingsPerSide": 360})
    assert source.calls[0] == ("katowice", "sale", 360, None)


@pytest.mark.asyncio
async def test_charge_limit_stops_cleanly_with_free_records_and_best_deals() -> None:
    actor = FakeActor(capacity={"area-yield": 0, "scored-listing": 3})
    actor, _, summary = await _run({"cities": ["katowice"]}, actor=actor)

    assert actor.failed is None
    assert summary["chargeLimitReached"] is True and summary["status"] == "partial"
    assert "maximum charge" in summary["note"]
    charged_events = {e for e, _ in actor.pushed if e is not None}
    assert "area-yield" not in charged_events                 # nothing affordable, never sent
    area = actor.records("areaYield")
    assert area and all(r["confidence"] == "low" for r in area)  # free context still delivered
    scored = actor.records("scoredListing")
    assert len(scored) == 3
    assert summary["events"]["scored-listing"]["pushed"] == 3
    assert summary["events"]["scored-listing"]["chargeable"] > 3
    assert actor.statuses[-1].startswith("Stopped at your maximum charge")

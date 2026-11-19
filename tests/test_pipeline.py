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
        self.capacity = capacity  # remaining chargeable count per event; None = not pay-per-event
        self.state: dict[str, dict] = {}
        self.max_charge: float | None = None
        self.tracked: dict | None = None

    async def push(self, records: list[dict], event: str | None) -> tuple[int, bool]:
        async def pusher(batch: list[dict], charged_event: str | None) -> int:
            self.pushed.append((charged_event, list(batch)))
            if charged_event is not None and self.capacity is not None and charged_event in self.capacity:
                self.capacity[charged_event] -= len(batch)
            return len(batch)
        return await push_with_charging(
            pusher, records, event,
            is_pay_per_event=self.capacity is not None,
            capacity=lambda e: None if self.capacity is None or e is None else self.capacity.get(e),
        )

    def charged_count(self, event: str) -> int | None:
        return None

    def charging_info(self) -> dict:
        return {"isPayPerEvent": self.capacity is not None, "maxChargeUsd": self.max_charge, "memoryMbytes": 512}

    def track(self, summary: dict) -> None:
        self.tracked = summary

    async def load_state(self, key: str) -> dict:
        return copy.deepcopy(self.state.get(key, {}))

    async def save_state(self, key: str, state: dict) -> None:
        self.state[key] = copy.deepcopy(state)

    async def set_value(self, key: str, value: dict) -> None:
        self.kv[key] = copy.deepcopy(value)

    async def fail(self, message: str) -> None:
        self.failed = message

    async def status(self, message: str) -> None:
        self.statuses.append(message)

    def records(self, record_type: str) -> list[dict]:
        return [r for _, batch in self.pushed for r in batch if r["recordType"] == record_type]


class FakeSource:
    def __init__(self, blocked: set[str] = frozenset(), empty: set[str] = frozenset(), mutate=None) -> None:
        self.blocked = blocked
        self.empty = empty
        self.mutate = mutate
        self.calls: list[tuple[str, str, int, int | None]] = []

    async def fetch_listings(self, city_key, transaction, max_listings, max_per_district=None):
        self.calls.append((city_key, transaction, max_listings, max_per_district))
        if city_key in self.blocked:
            raise BlockedError(f"www.otodom.pl blocked 9 of 11 requests ({city_key} {transaction})")
        items = [] if city_key in self.empty else copy.deepcopy(ITEMS[transaction])
        if self.mutate:
            self.mutate(items, transaction)
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


MONITOR = {"cities": ["katowice"], "onlyNewOrChanged": True, "stateKey": "watch-1", "mode": "scoreListings"}


@pytest.mark.asyncio
async def test_monitoring_first_run_marks_everything_new_and_saves_state() -> None:
    actor, _, summary = await _run(MONITOR)
    scored = actor.records("scoredListing")
    assert scored and {r["changeType"] for r in scored} == {"new"}
    assert all(r["firstSeenAt"] == "2026-11-18" for r in scored)
    assert len(actor.state["watch-1"]) == len(scored)
    assert summary["monitoring"]["new"] == len(scored)


@pytest.mark.asyncio
async def test_monitoring_quiet_rerun_succeeds_with_nothing_to_charge() -> None:
    actor = FakeActor()
    await _run(MONITOR, actor=actor)
    actor.pushed.clear()
    _, _, summary = await _run(MONITOR, actor=actor)
    assert actor.failed is None
    assert actor.pushed == []
    assert summary["status"] == "ok" and summary["monitoring"]["unchanged"] > 0
    assert actor.statuses[-1] == "No new or cheaper listings since the last run."


@pytest.mark.asyncio
async def test_monitoring_reports_only_the_price_cut() -> None:
    actor = FakeActor()
    await _run(MONITOR, actor=actor)
    first = actor.records("scoredListing")
    target_url = first[0]["url"]
    slug = target_url.rsplit("/", 1)[-1]

    def cut(items, tx):
        for it in items:
            if it.get("slug") == slug:
                it["totalPrice"]["value"] = round(it["totalPrice"]["value"] * 0.95)

    actor.pushed.clear()
    _, _, summary = await _run(MONITOR, FakeSource(mutate=cut), actor=actor)
    scored = actor.records("scoredListing")
    assert [r["url"] for r in scored] == [target_url]
    assert scored[0]["changeType"] == "priceCut" and scored[0]["priceCutPct"] == pytest.approx(5.0, abs=0.1)
    assert scored[0]["firstSeenAt"] == "2026-11-18"


@pytest.mark.asyncio
async def test_listings_held_back_by_the_limit_stay_new_for_the_next_run() -> None:
    actor = FakeActor(capacity={"area-yield": 0, "scored-listing": 2})
    _, _, first = await _run(MONITOR, actor=actor)
    total_new = first["monitoring"]["new"]
    assert first["monitoring"]["heldBack"] == total_new - 2
    assert len(actor.state["watch-1"]) == 2

    actor.capacity = None
    actor.pushed.clear()
    _, _, second = await _run(MONITOR, actor=actor)
    assert second["monitoring"]["new"] == total_new - 2


def test_scored_listing_without_monitoring_has_null_change_fields() -> None:
    import asyncio
    actor, _, _ = asyncio.run(_run({"cities": ["katowice"], "mode": "scoreListings"}))
    rec = actor.records("scoredListing")[0]
    assert (rec["changeType"], rec["priceCutPct"], rec["firstSeenAt"]) == (None, None, None)


@pytest.mark.asyncio
async def test_run_summary_has_charging_context_totals_and_side_fields() -> None:
    actor, _, summary = await _run({"cities": ["katowice"]})
    stored = actor.kv["RUN_SUMMARY"]
    assert actor.tracked is summary
    assert stored["isPayPerEvent"] is False and stored["maxChargeUsd"] is None
    assert {"startedAt", "finishedAt", "timeS", "fx", "input", "events", "records", "totals"} <= set(stored)
    side = stored["cities"]["katowice"]["sides"]["sale"]
    for key in ("pages", "rawItems", "cleanedItems", "rejected", "primaryMarketProjects", "requests", "blocked",
                "blockedPct", "bytes", "timeS", "sample", "proxySessions", "buildIdRefreshes", "fallbackToHtml"):
        assert key in side, key
    assert {"medianAgeDays", "oldestListingDays", "share"} <= set(side["sample"])
    assert side["primaryMarketProjects"] == 8
    assert stored["totals"]["citiesOk"] == 1
    assert {"computedAt", "fx", "cities"} <= set(actor.kv["YIELD_REPORT"])


@pytest.mark.asyncio
async def test_failed_run_summary_is_stamped_too() -> None:
    actor, _, _ = await _run({"cities": ["warszawa"]}, FakeSource(blocked={"warszawa"}))
    stored = actor.kv["RUN_SUMMARY"]
    assert stored["status"] == "failed" and "finishedAt" in stored
    assert stored["totals"]["citiesFailed"] == 1


def test_dataset_views_reference_fields_the_records_actually_have() -> None:
    import asyncio
    schema = json.loads((Path(__file__).parent.parent / ".actor" / "dataset_schema.json").read_text())
    actor, _, _ = asyncio.run(_run({"cities": ["katowice"]}))
    for view, record_type in (("yieldByDistrict", "areaYield"), ("scoredListings", "scoredListing")):
        fields = schema["views"][view]["transformation"]["fields"]
        present = set().union(*(r.keys() for r in actor.records(record_type)))
        assert set(fields) <= present, (view, set(fields) - present)
        assert set(schema["views"][view]["display"]["properties"]) == set(fields)


@pytest.mark.asyncio
async def test_budget_mode_a_tiny_max_charge_runs_one_city_in_city_mode_and_succeeds() -> None:
    actor = FakeActor(capacity={"area-yield": 0, "scored-listing": 2})  # what $0.01 affords
    actor.max_charge = 0.01
    actor, source, summary = await _run({"cities": ["warszawa", "krakow"]}, actor=actor)

    assert actor.failed is None
    assert summary["budgetReduced"] is True and summary["maxChargeUsd"] == 0.01
    assert summary["estimatedAuthorCostUsd"] < summary["requestedScopeCostUsd"]
    assert source.calls == [("warszawa", "sale", 360, None), ("warszawa", "rent", 360, None)]
    assert summary["input"]["samplingMode"] == "city" and summary["input"]["cities"] == ["warszawa"]
    assert actor.records("areaYield") or actor.records("scoredListing")   # non-empty dataset
    assert any("Max charge too low" in s for s in actor.statuses)


@pytest.mark.asyncio
async def test_budget_mode_keeps_dataset_non_empty_even_for_score_only_input() -> None:
    actor = FakeActor(capacity={"area-yield": 0, "scored-listing": 0})
    actor.max_charge = 0.001
    actor, _, summary = await _run({"cities": ["katowice"], "mode": "scoreListings"}, actor=actor)
    assert actor.failed is None and summary["budgetReduced"] is True
    assert actor.records("areaYield")  # free city-level context


@pytest.mark.parametrize("ppe, max_charge", [(False, 0.01), (True, None)])
@pytest.mark.asyncio
async def test_budget_mode_b_no_limit_or_not_pay_per_event_is_not_reduced(ppe: bool, max_charge) -> None:
    actor = FakeActor(capacity={} if ppe else None)
    actor.max_charge = max_charge
    actor, source, summary = await _run({"cities": ["warszawa", "krakow"]}, actor=actor)
    assert summary["budgetReduced"] is False
    assert [c[0] for c in source.calls] == ["warszawa", "warszawa", "krakow", "krakow"]
    assert source.calls[0][3] == 0  # per-district, automatic quota


@pytest.mark.asyncio
async def test_budget_mode_c_sufficient_limit_is_not_reduced() -> None:
    actor = FakeActor(capacity={})
    actor.max_charge = 50.0
    actor, source, summary = await _run({"cities": ["warszawa", "krakow"]}, actor=actor)
    assert summary["budgetReduced"] is False
    assert summary["minMaxChargeUsd"] < 50.0
    assert len(source.calls) == 4


@pytest.mark.asyncio
async def test_max_scored_listings_keeps_the_best_deals_after_filters() -> None:
    actor_all, _, all_summary = await _run({"cities": ["katowice"], "mode": "scoreListings", "maxScoredListings": 0})
    best = [r["url"] for r in actor_all.records("scoredListing")]
    actor, _, summary = await _run({"cities": ["katowice"], "mode": "scoreListings", "maxScoredListings": 3})
    assert [r["url"] for r in actor.records("scoredListing")] == best[:3]
    assert summary["scoredAvailable"] == len(best) == all_summary["scoredReturned"]
    assert summary["scoredReturned"] == 3
    assert summary["events"]["scored-listing"]["chargeable"] == 3


@pytest.mark.asyncio
async def test_listings_cut_by_max_scored_are_not_marked_seen() -> None:
    actor = FakeActor()
    _, _, first = await _run({**MONITOR, "maxScoredListings": 2}, actor=actor)
    assert first["scoredReturned"] == 2 and len(actor.state["watch-1"]) == 2
    assert first["monitoring"]["heldBack"] == first["scoredAvailable"] - 2


@pytest.mark.asyncio
async def test_prefill_run_flag() -> None:
    from src.inputs import PREFILL_INPUT
    _, _, prefill = await _run(dict(PREFILL_INPUT, cities=["warszawa"]))
    _, _, default = await _run({"cities": ["katowice"]})
    assert prefill["prefillRun"] is True and default["prefillRun"] is False

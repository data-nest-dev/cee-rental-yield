from __future__ import annotations

import copy
import re
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
        self.by_dataset: dict[str | None, list[dict]] = {}  # alias (None = default) -> records
        self.kv: dict[str, dict] = {}
        self.failed: str | None = None
        self.statuses: list[str] = []
        self.capacity = capacity  # remaining chargeable count per event; None = not pay-per-event
        self.state: dict[str, dict] = {}
        self.max_charge: float | None = None
        self.tracked: dict | None = None

    async def push(self, records: list[dict], event: str | None, on_pushed=None, dataset: str | None = None) -> tuple[int, bool]:
        async def pusher(batch: list[dict], charged_event: str | None) -> int:
            self.pushed.append((charged_event, list(batch)))
            self.by_dataset.setdefault(dataset, []).extend(batch)
            if charged_event is not None and self.capacity is not None and charged_event in self.capacity:
                self.capacity[charged_event] -= len(batch)
            return len(batch)
        return await push_with_charging(
            pusher, records, event,
            is_pay_per_event=self.capacity is not None,
            capacity=lambda e: None if self.capacity is None or e is None else self.capacity.get(e),
            on_pushed=on_pushed,
        )

    def charged_count(self, event: str) -> int | None:
        return None

    def charging_info(self) -> dict:
        return {"isPayPerEvent": self.capacity is not None, "maxChargeUsd": self.max_charge, "memoryMbytes": 512}

    def track(self, summary: dict, yield_report: dict | None = None) -> None:
        self.tracked = summary
        self.tracked_report = yield_report

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
        seen: set[int] = set()  # the yieldReport copy to `yields` pushes the same objects again
        return [r for _, batch in self.pushed for r in batch if r["recordType"] == record_type and not (id(r) in seen or seen.add(id(r)))]


class FakeSource:
    def __init__(self, blocked: set[str] = frozenset(), empty: set[str] = frozenset(), mutate=None,
                 replicate: int = 1) -> None:
        self.blocked = blocked
        self.empty = empty
        self.mutate = mutate
        self.replicate = replicate
        self.calls: list[tuple[str, str, int, int | None]] = []

    async def fetch_listings(self, city_key, transaction, max_listings, max_per_district=None):
        self.calls.append((city_key, transaction, max_listings, max_per_district))
        if city_key in self.blocked:
            raise BlockedError(f"www.otodom.pl blocked 9 of 11 requests ({city_key} {transaction})")
        items = [] if city_key in self.empty else copy.deepcopy(ITEMS[transaction])
        if self.replicate > 1:
            # more listings per group, so charged district/room groups exist (unique slugs, same data)
            base = items
            items = []
            for n in range(self.replicate):
                for it in copy.deepcopy(base):
                    it["slug"] = f"{it.get('slug')}-r{n}"
                    it["id"] = f"{it.get('id')}{n}"
                    if it.get("areaInSquareMeters"):  # distinct areas, or rent reposts would be deduplicated
                        it["areaInSquareMeters"] = round(it["areaInSquareMeters"] + n * 0.01, 2)
                    items.append(it)
        if self.mutate:
            self.mutate(items, transaction)
        # The fixtures are Katowice listings; re-home them so any configured city accepts them.
        from src.config import CITIES
        target = CITIES[city_key].location_path
        for it in items:
            # fixtures are Katowice listings: drop the city name from slug/title so the location check accepts them
            it["slug"] = re.sub(r"katowic\w*", "miasto", it.get("slug", ""))
            if isinstance(it.get("title"), str):
                it["title"] = re.sub(r"(?i)katowic\w*", "Miasto", it["title"])
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

    assert actor.failed and "no result events were charged" in actor.failed
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
    # scoreListings: YIELD_REPORT carries only the free city-level context, never paid groups
    groups = [g for c in actor.kv["YIELD_REPORT"]["cities"].values() for g in c["groups"]]
    assert groups and all(g["confidence"] == "low" for g in groups)
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


MONITOR = {"cities": ["katowice"], "onlyNewOrChanged": True, "watchlistName": "watch-1", "mode": "scoreListings"}


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
            if re.sub(r"katowic\w*", "miasto", it.get("slug", "")) == slug:
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


from decimal import Decimal

from src.charging import affordable_count

PLATFORM_PRICES = {"area-yield": Decimal("0.02"), "scored-listing": Decimal("0.004"),
                   "apify-actor-start": Decimal("0.00005")}  # no apify-default-dataset-item (removed in Console)


class PlatformPricedActor(FakeActor):
    """Charges like the platform: start fee already charged, per-event prices, strictly-below capacity."""

    def __init__(self, max_usd: str) -> None:
        super().__init__()
        self.max_usd = Decimal(max_usd)
        self.max_charge = float(self.max_usd)
        self.charged_usd = PLATFORM_PRICES["apify-actor-start"]
        self.charges: dict[str, int] = {"apify-actor-start": 1}

    def charging_info(self) -> dict:
        return {"isPayPerEvent": True, "maxChargeUsd": self.max_charge, "memoryMbytes": 512}

    def charged_count(self, event: str) -> int | None:
        return self.charges.get(event, 0)

    async def push(self, records, event, on_pushed=None, dataset=None):
        async def pusher(batch, charged_event):
            self.pushed.append((charged_event, list(batch)))
            if charged_event is not None:
                self.charges[charged_event] = self.charges.get(charged_event, 0) + len(batch)
                self.charged_usd += PLATFORM_PRICES[charged_event] * len(batch)
            return len(batch)

        def capacity(e):
            price = PLATFORM_PRICES.get(e, Decimal(0)) if e is not None else Decimal(0)
            return affordable_count(self.max_usd, self.charged_usd, price)

        return await push_with_charging(pusher, records, event, is_pay_per_event=True,
                                        capacity=capacity, on_pushed=on_pushed)


@pytest.mark.parametrize("mode", ["both", "scoreListings"])
@pytest.mark.asyncio
async def test_platform_prices_with_one_cent_limit(mode: str) -> None:
    actor = PlatformPricedActor("0.01")
    actor, _, summary = await _run({"cities": ["warszawa", "krakow"], "mode": mode}, actor=actor)

    assert actor.failed is None and summary["budgetReduced"] is True
    events = [e for e, _ in actor.pushed]
    assert "area-yield" not in events                       # never affordable at $0.02, never attempted
    area, scored = actor.records("areaYield"), actor.records("scoredListing")
    assert area and all(r["confidence"] == "low" for r in area)   # free city context, in both modes
    assert len(scored) == 2                                  # 0.00995 left -> 2 x $0.004
    best = sorted((r["dealScore"] for r in scored), reverse=True)
    assert [r["dealScore"] for r in scored] == best
    assert actor.charges == {"apify-actor-start": 1, "scored-listing": 2}
    assert actor.charged_usd == Decimal("0.00805") < actor.max_usd
    assert summary["chargeLimitReached"] is True


@pytest.mark.asyncio
async def test_limit_reached_mid_way_leaves_no_unpushed_groups_in_reports() -> None:
    actor = FakeActor(capacity={"area-yield": 2, "scored-listing": 0})
    actor, _, summary = await _run({"cities": ["katowice"]}, FakeSource(replicate=8), actor=actor)  # 4 charged groups

    charged_in_dataset = [r for r in actor.records("areaYield") if r["confidence"] != "low"]
    assert len(charged_in_dataset) == 2
    report_groups = [g for c in actor.kv["YIELD_REPORT"]["cities"].values() for g in c["groups"]]
    pushed = actor.records("areaYield")
    assert len(report_groups) == len(pushed)
    assert all(g in pushed for g in report_groups)          # no unpushed (unpaid) group in the KV report
    assert actor.tracked_report["cities"] == actor.kv["YIELD_REPORT"]["cities"]  # what an abort would write
    assert summary["events"]["area-yield"]["chargeable"] > 2


@pytest.mark.asyncio
async def test_preliminary_summary_has_no_yield_values_or_prices() -> None:
    snapshots = []

    class Snap(FakeActor):
        async def set_value(self, key, value):
            if key == "RUN_SUMMARY" and value.get("status") == "pushing":
                snapshots.append(json.dumps(value))
            await super().set_value(key, value)

    await _run({"cities": ["katowice"]}, actor=Snap())
    assert snapshots
    prelim = snapshots[0]
    for forbidden in ("grossYieldPct", "salePricePerM2Eur", "rentPerM2MonthlyEur", "dealScore", "pricePerM2Eur"):
        assert forbidden not in prelim


@pytest.mark.parametrize("mode, expect_yields", [("both", True), ("scoreListings", False)])
@pytest.mark.asyncio
async def test_monitoring_yields_follow_mode(mode: str, expect_yields: bool) -> None:
    actor, _, _ = await _run({**MONITOR, "mode": mode})
    assert bool(actor.records("areaYield")) is expect_yields
    assert actor.records("scoredListing")


@pytest.mark.asyncio
async def test_primary_market_setting_selects_portal_filter_and_labels() -> None:
    actor, source, _ = await _run({"cities": ["katowice"], "includePrimaryMarket": False})
    assert source.market == "SECONDARY"
    scored = actor.records("scoredListing")
    assert scored and {r["isPrimaryMarket"] for r in scored} == {False}

    actor, source, _ = await _run({"cities": ["katowice"]})
    assert source.market == "ALL"
    scored = actor.records("scoredListing")
    assert {r["isPrimaryMarket"] for r in scored} <= {True, None}
    assert None in {r["isPrimaryMarket"] for r in scored}


def test_sort_scored_breaks_score_ties_by_discount() -> None:
    from src.pipeline import sort_scored
    recs = [(None, {"dealScore": 100, "discountVsMedianPct": d, "id": i}) for i, d in enumerate([20.0, 49.4, 35.0])]
    recs.append((None, {"dealScore": 99, "discountVsMedianPct": 60.0, "id": 9}))
    assert [r["id"] for _, r in sort_scored(recs)] == [1, 2, 0, 9]


@pytest.mark.asyncio
async def test_rent_side_reports_near_duplicate_share() -> None:
    def twin_rents(items, transaction):
        if transaction == "rent":
            for it in items[1:]:
                for k in ("areaInSquareMeters", "totalPrice", "floorNumber", "roomsNumber", "isPrivateOwner"):
                    it[k] = copy.deepcopy(items[0].get(k))
                it["location"] = copy.deepcopy(items[0]["location"])
    _, _, summary = await _run({"cities": ["katowice"]}, source=FakeSource(mutate=twin_rents))
    sides = summary["cities"]["katowice"]["sides"]
    assert sides["rent"]["rejected"]["near_duplicate_rent"] > 0
    assert 0 < sides["rent"]["nearDuplicateRentShare"] <= 1
    assert "nearDuplicateRentShare" not in sides["sale"]


# --- M4: areaYield records go to the "yields" dataset (default dataset keeps the API-friendly scored listings) ---

@pytest.mark.asyncio
@pytest.mark.parametrize("mode, yields_alias", [("both", "yields"), ("scoreListings", "yields"), ("yieldReport", None)])
async def test_yields_dataset_routing_by_mode(mode: str, yields_alias: str | None) -> None:
    actor, _, summary = await _run({"cities": ["katowice"], "mode": mode}, actor=FakeActor(capacity={"area-yield": 99, "scored-listing": 99}))
    assert all(r["recordType"] == "areaYield" for r in actor.by_dataset.get("yields", []))
    if mode != "scoreListings":                      # scoreListings pushes no yields outside budget mode
        assert actor.by_dataset[yields_alias] and actor.records("areaYield") == [
            r for r in actor.by_dataset[yields_alias] if r["recordType"] == "areaYield"]
    if mode == "yieldReport":
        # default keeps the yields (API); `yields` gets a free copy for the Output tab view
        assert set(actor.by_dataset) == {None, "yields"} and summary["yieldsDataset"] == "default"
        assert actor.by_dataset["yields"] == actor.by_dataset[None]
        charged = sum(len(b) for e, b in actor.pushed if e == "area-yield")
        assert charged == summary["events"]["area-yield"]["pushed"] == summary["events"]["area-yield"]["chargeable"]  # copy never charged
    else:
        assert all(r["recordType"] == "scoredListing" for r in actor.by_dataset.get(None, []))
        assert actor.by_dataset.get(None) and summary["yieldsDataset"] == "yields"
        ys = actor.by_dataset.get(yields_alias, [])
        assert len({id(r) for r in ys}) == len(ys)  # no copy pass
        assert all(r["recordType"] == "scoredListing" for r in actor.by_dataset[None])


@pytest.mark.asyncio
async def test_budget_mode_free_context_goes_to_yields_dataset_and_default_stays_scored() -> None:
    actor = FakeActor(capacity={"area-yield": 0, "scored-listing": 2})
    actor.max_charge = 0.01
    await _run({"cities": ["katowice"], "mode": "scoreListings"}, actor=actor)
    assert all(r["recordType"] == "areaYield" and r["confidence"] == "low" for r in actor.by_dataset.get("yields", []))
    assert all(r["recordType"] == "scoredListing" for r in actor.by_dataset[None])


# --- M4: monitoring falls back to a plain run when the named state store is unavailable ---

class StateBrokenActor(FakeActor):
    def __init__(self, load: bool = False, save: bool = False) -> None:
        super().__init__()
        self.break_load, self.break_save = load, save

    async def load_state(self, key: str) -> dict:
        if self.break_load:
            raise PermissionError("named store not accessible")
        return await super().load_state(key)

    async def save_state(self, key: str, state: dict) -> None:
        if self.break_save:
            raise PermissionError("named store not accessible")
        await super().save_state(key, state)


@pytest.mark.asyncio
async def test_monitoring_load_failure_warns_and_runs_without_state() -> None:
    actor = StateBrokenActor(load=True)
    _, _, summary = await _run(MONITOR, actor=actor)
    scored = actor.records("scoredListing")
    assert actor.failed is None and summary["status"] == "ok" and scored
    assert all(r["changeType"] is None for r in scored)           # no change detection without state
    assert summary["monitoring"]["stateAvailable"] is False and "PermissionError" in summary["monitoring"]["warning"]
    assert actor.state == {}


@pytest.mark.asyncio
async def test_monitoring_save_failure_is_a_warning_after_delivery() -> None:
    actor = StateBrokenActor(save=True)
    _, _, summary = await _run(MONITOR, actor=actor)
    assert actor.failed is None and summary["status"] == "ok" and actor.records("scoredListing")
    assert summary["monitoring"]["stateAvailable"] is False and "could not be saved" in summary["monitoring"]["warning"]


# --- M4: proxy refusal fails the run with a clear message and charges nothing ---

@pytest.mark.asyncio
async def test_proxy_creation_failure_fails_with_clear_message() -> None:
    from src.http import PROXY_ACCESS_MESSAGE, ProxyAccessError

    async def refusing(run_input):
        raise ProxyAccessError(PROXY_ACCESS_MESSAGE)

    actor = FakeActor()
    summary = await run(actor, {"cities": ["katowice"]}, http_factory=refusing, source_factory=lambda h: FakeSource(),
                        rates_loader=_rates, as_of=AS_OF)
    assert summary["status"] == "failed" and "no access to the selected proxy group" in summary["reason"]
    assert actor.failed and "no result events were charged" in actor.failed and actor.pushed == []


@pytest.mark.asyncio
async def test_proxy_refusal_during_fetch_fails_the_run_not_just_the_city() -> None:
    from src.http import ProxyAccessError

    class Refused(FakeSource):
        async def fetch_listings(self, *a, **k):
            raise ProxyAccessError("Apify Proxy refused the connection (HTTP 407/597)")

    actor = FakeActor()
    summary = await run(actor, {"cities": ["katowice", "krakow"]}, http_factory=_http,
                        source_factory=lambda h: Refused(), rates_loader=_rates, as_of=AS_OF)
    assert summary["status"] == "failed" and "krakow" not in summary["cities"]
    assert actor.failed and actor.pushed == []


# --- Quiet monitoring run: state refreshed, summary shape identical to a run with records ---

@pytest.mark.asyncio
async def test_quiet_monitoring_run_refreshes_last_seen_so_pruning_keeps_active_listings() -> None:
    actor = FakeActor()
    await run(actor, MONITOR, http_factory=_http, source_factory=lambda h: FakeSource(), rates_loader=_rates, as_of=date(2026, 11, 1))
    first = copy.deepcopy(actor.state["watch-1"])
    summary = await run(actor, MONITOR, http_factory=_http, source_factory=lambda h: FakeSource(), rates_loader=_rates, as_of=date(2026, 12, 20))
    state = actor.state["watch-1"]
    assert summary["records"] == {"areaYield": 0, "scoredListing": 0} and set(state) == set(first)
    assert all(v["lastSeenAt"] == "2026-12-20" and v["firstSeenAt"] == "2026-11-01" for v in state.values())
    assert summary["monitoring"]["savedListings"] == len(state) and summary["monitoring"]["heldBack"] == 0
    # 79 days after the first run: without the refresh these entries would be older than the 60-day cut-off
    third = await run(actor, MONITOR, http_factory=_http, source_factory=lambda h: FakeSource(), rates_loader=_rates, as_of=date(2027, 1, 20))
    assert third["monitoring"]["new"] == 0 and third["monitoring"]["unchanged"] == len(first)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["scoreListings", "both"])
async def test_run_summary_keys_do_not_depend_on_the_number_of_records(mode: str) -> None:
    cfg = dict(MONITOR, mode=mode)
    actor = FakeActor()
    _, _, with_records = await _run(cfg, actor=actor)
    _, _, quiet = await _run(cfg, actor=actor)
    assert quiet["records"]["scoredListing"] == 0 < with_records["records"]["scoredListing"]
    if mode == "scoreListings":      # yields follow mode in monitoring: `both` returns them on every run
        assert quiet["records"]["areaYield"] == 0
    assert set(quiet) - {"finishedAt"} == set(with_records) - {"finishedAt"}
    assert set(quiet["monitoring"]) == set(with_records["monitoring"])
    assert set(quiet["events"]) == set(with_records["events"])
    assert quiet["events"]["scored-listing"]["pushed"] == 0 and quiet["chargeLimitReached"] is False
    assert quiet["yieldsDataset"] == with_records["yieldsDataset"]


@pytest.mark.asyncio
@pytest.mark.parametrize("include_primary,market", [(True, "ALL"), (False, "SECONDARY")])
async def test_run_summary_sides_report_market_and_identical_merged(include_primary: bool, market: str) -> None:
    _, _, summary = await _run({"cities": ["katowice"], "includePrimaryMarket": include_primary})
    sides = summary["cities"]["katowice"]["sides"]
    assert sides["sale"]["market"] == market and sides["rent"]["market"] == market
    assert isinstance(sides["sale"]["identicalMerged"], int) and "identicalMerged" not in sides["rent"]


def test_identical_merged_on_fixtures_and_clones() -> None:
    from src.clean import clean_listings
    from src.config import CITIES
    from src.sources.otodom import parse_otodom_items
    cfg = CITIES["katowice"]
    raw = copy.deepcopy(ITEMS["sale"])
    clones = []
    for n, it in enumerate(raw):
        if it.get("estate") == "FLAT" and it.get("totalPrice") and not it["href"].startswith("hpr/"):
            c = copy.deepcopy(it)
            c["slug"], c["id"] = f"{it['slug']}-clone", int(it["id"]) + 10_000_000
            clones.append(c)
            break
    base, _ = parse_otodom_items(raw, cfg, "sale")
    both, _ = parse_otodom_items(raw + clones, cfg, "sale")
    c0: dict = {}
    c1: dict = {}
    clean_listings(base, counters=c0)
    cleaned, _ = clean_listings(both, counters=c1)
    assert c0.get("identical_merged", 0) == 0 and c1["identical_merged"] == 1
    assert any(ls.identical_ids == (str(clones[0]["id"]),) for ls in cleaned)


def test_monitoring_group_is_not_new_when_the_representative_changes() -> None:
    import dataclasses
    from src.pipeline import _price_map, apply_monitoring
    from tests.test_clean import _make_listing
    members = [_make_listing(dedup_key=f"s{i}", listing_id=str(i)) for i in (5, 7)]
    first = dataclasses.replace(members[0], identical_ids=("7",), identical_keys=("s7",))
    rec = {"dealScore": 50, "discountVsMedianPct": 0.0, "daysOnMarket": 1}
    state = {}
    from src.monitor import update_state
    state = update_state(state, _price_map([(first, rec)]), date(2026, 11, 1))
    assert set(state) == {"s5", "s7"}
    # listing 5 sold, 7 is now the representative and a lower ID 3 has appeared; neither is "new"
    now = dataclasses.replace(_make_listing(dedup_key="s3", listing_id="3"), identical_ids=("7",), identical_keys=("s7",))
    changed, unchanged = apply_monitoring([(now, dict(rec))], state, date(2026, 11, 20))
    assert not changed and unchanged[0][1]["changeType"] == "unchanged"
    assert unchanged[0][1]["firstSeenAt"] == "2026-11-01"
    brand_new = _make_listing(dedup_key="zz", listing_id="1")
    changed, _ = apply_monitoring([(brand_new, dict(rec))], state, date(2026, 11, 20))
    assert changed[0][1]["changeType"] == "new"


def test_suspect_rooms_listing_is_compared_at_city_level_only() -> None:
    from src.stats import group_keys
    from tests.test_clean import _make_listing
    odd = _make_listing(rooms=7, area_m2=27.0, flags=("suspectRooms",))
    assert [level for level, _ in group_keys(odd)] == ["city"]
    assert [level for level, _ in group_keys(_make_listing(rooms=2))] == ["district", "city_rooms", "city"]

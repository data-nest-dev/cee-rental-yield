from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Protocol

from src.charging import AREA_YIELD_EVENT, CHARGED_CONFIDENCE, SCORED_LISTING_EVENT
from src.clean import clean_listings
from src.config import CITIES
from src.fx import parse_ecb_rates
from src.http import BlockedError, HttpClient
from src.inputs import ROOM_BUCKETS, InputError, RunInput, parse_input
from src.models import Listing
from src.output import build_area_yield, build_scored_listing, build_side_summary
from src.sources.otodom import DOMAIN, OtodomSource, parse_otodom_items
from src.stats import (
    SideCoverage, area_sample, compute_groups, district_group_coverage, gate_coverage,
    index_groups, resolve_comparables, rooms_bucket, sample_stats,
)

logger = logging.getLogger(__name__)

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
SOURCE_NAMES = ["otodom"]
SIDES = ("sale", "rent")


class ActorPort(Protocol):
    """What the pipeline needs from the platform; main.py adapts apify.Actor, tests use a fake."""

    async def push(self, records: list[dict], event: str | None) -> tuple[int, bool]: ...
    def charged_count(self, event: str) -> int | None: ...
    async def set_value(self, key: str, value: dict) -> None: ...
    async def fail(self, message: str) -> None: ...
    async def status(self, message: str) -> None: ...


@dataclass
class CityResult:
    key: str
    name: str
    status: str = "ok"
    reason: str | None = None
    sides: dict[str, dict] = field(default_factory=dict)
    cleaned: list[Listing] = field(default_factory=list)
    coverage: dict[str, SideCoverage] = field(default_factory=dict)


@dataclass
class CityOutput:
    area_records: list[dict]
    report_groups: list[dict]
    scored: list[tuple[Listing, dict]]
    gate: dict | None
    groups_info: dict | None


async def fetch_rates(http: HttpClient) -> tuple[dict[str, float], str]:
    status, body = await http.get(ECB_URL)
    if status != 200:
        raise RuntimeError(f"ECB rates returned HTTP {status}")
    return parse_ecb_rates(body)


async def fetch_city(http: HttpClient, source: OtodomSource, city_key: str, run_input: RunInput, as_of: date) -> CityResult:
    cfg = CITIES[city_key]
    result = CityResult(key=city_key, name=cfg.display_name)
    for tx in SIDES:
        ds = http.domain_stats.get(DOMAIN)
        bytes0 = ds.bytes_downloaded if ds else 0
        t0 = time.monotonic()
        try:
            raw, stats = await source.fetch_listings(
                city_key, tx, run_input.max_listings_per_side, max_per_district=run_input.max_per_district_arg(),
            )
        except BlockedError as e:
            return _failed(result, f"{tx}: blocked ({e})")
        except Exception as e:  # network or portal failure after retries; listing content never logged
            return _failed(result, f"{tx}: fetch failed ({type(e).__name__}: {e})")
        listings, rejected = parse_otodom_items(raw, cfg, tx)
        cleaned, clean_rejected = clean_listings(listings)
        elapsed = time.monotonic() - t0
        window = http.window(DOMAIN)
        requests = window.requests if window else 0
        blocked = window.blocked if window else 0
        sample = sample_stats(cleaned, as_of, stats.get("fetched_items", 0), stats.get("total_items"))
        summary = build_side_summary(stats, rejected, clean_rejected, len(cleaned), requests, blocked, elapsed, sample=sample)
        ds = http.domain_stats.get(DOMAIN)
        summary.update({
            "blockedPct": round(blocked / requests * 100, 1) if requests else 0.0,
            "bytes": (ds.bytes_downloaded if ds else 0) - bytes0,
            "quotaPerDistrict": stats.get("quota_per_district"),
            "htmlPages": stats.get("html_pages", 0),
            "fallbackRecoveries": stats.get("fallback_recoveries", 0),
            "proxySessions": dict(window.sessions) if window else {},
        })
        result.sides[tx] = summary
        result.cleaned.extend(cleaned)
        result.coverage[tx] = SideCoverage(
            fetched=stats.get("fetched_items", 0),
            total=stats.get("total_items"),
            fetched_by_district=stats.get("fetched_by_district") or {},
            total_by_district=stats.get("district_total_items") or {},
        )
    if not any(ls.transaction == "sale" for ls in result.cleaned):
        return _failed(result, "no listings for sale after cleaning")
    return result


def _failed(result: CityResult, reason: str) -> CityResult:
    result.status = "failed"
    result.reason = reason
    result.cleaned = []
    logger.warning("City %s skipped: %s", result.key, reason)
    return result


def compute_city(city: CityResult, run_input: RunInput, rates: dict[str, float], fx_date: str, as_of: date) -> CityOutput:
    listings = [
        ls for ls in city.cleaned
        if run_input.area_min <= ls.area_m2 <= run_input.area_max
        and (run_input.include_primary_market or not ls.is_primary_market)
    ]
    all_rooms = set(run_input.rooms) == set(ROOM_BUCKETS)

    area_records: list[dict] = []
    report_groups: list[dict] = []
    if run_input.wants_yields:
        for g in compute_groups(listings, run_input.min_sale_sample, run_input.min_rent_sample):
            rec = build_area_yield(g, rates, fx_date, SOURCE_NAMES, sample=area_sample(g, as_of, city.coverage))
            report_groups.append(rec)
            if g.rooms_bucket == "all" or g.rooms_bucket in run_input.rooms:
                area_records.append(rec)

    scored: list[tuple[Listing, dict]] = []
    if run_input.wants_scores:
        index = index_groups(listings)
        for ls in listings:
            if ls.transaction != "sale":
                continue
            rb = rooms_bucket(ls.rooms)
            if not all_rooms and rb not in run_input.rooms:
                continue
            comp = resolve_comparables(ls, index, run_input.min_sale_sample, run_input.min_rent_sample)
            if comp is None:
                continue
            rec = build_scored_listing(ls, comp, rates)
            if rec["dealScore"] >= run_input.min_score:
                scored.append((ls, rec))

    return CityOutput(
        area_records=area_records,
        report_groups=report_groups,
        scored=scored,
        gate=gate_coverage(listings, run_input.min_sale_sample, run_input.min_rent_sample).get(city.name),
        groups_info=district_group_coverage(listings, run_input.min_sale_sample, run_input.min_rent_sample).get(city.name),
    )


def sort_scored(scored: list[tuple[Listing, dict]], output_currency: str) -> list[tuple[Listing, dict]]:
    """Best deals first: the dataset view cannot sort, and a cost-limited run keeps the head of this list."""
    def per_m2(item: tuple[Listing, dict]) -> float:
        ls, rec = item
        return rec["pricePerM2Eur"] if output_currency == "EUR" else ls.price_local / ls.area_m2
    return sorted(scored, key=lambda item: (-item[1]["dealScore"], per_m2(item)))


async def run(
    actor: ActorPort,
    raw_input: dict | None,
    *,
    http_factory: Callable[[RunInput], Awaitable[HttpClient]],
    source_factory: Callable[[HttpClient], OtodomSource] = OtodomSource,
    rates_loader: Callable[[HttpClient], Awaitable[tuple[dict[str, float], str]]] = fetch_rates,
    as_of: date | None = None,
) -> dict:
    as_of = as_of or date.today()
    started = time.monotonic()
    summary: dict = {
        "status": "running",
        "startedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cities": {},
    }

    try:
        run_input = parse_input(raw_input)
    except InputError as e:
        summary.update(status="failed", reason=f"Invalid input: {e}")
        await actor.set_value("RUN_SUMMARY", summary)
        await actor.fail(f"Invalid input: {e}")
        return summary
    http = await http_factory(run_input)
    try:
        return await _run(actor, run_input, summary, started, http, source_factory, rates_loader, as_of)
    finally:
        await http.close()


async def _run(
    actor: ActorPort,
    run_input: RunInput,
    summary: dict,
    started: float,
    http: HttpClient,
    source_factory: Callable[[HttpClient], OtodomSource],
    rates_loader: Callable[[HttpClient], Awaitable[tuple[dict[str, float], str]]],
    as_of: date,
) -> dict:
    summary["input"] = {
        "cities": run_input.cities, "mode": run_input.mode, "samplingMode": run_input.sampling_mode,
        "maxListingsPerDistrict": run_input.max_listings_per_district,
        "maxListingsPerSide": run_input.max_listings_per_side,
    }

    try:
        rates, fx_date = await rates_loader(http)
    except Exception as e:
        summary.update(status="failed", reason=f"ECB rates unavailable ({type(e).__name__})")
        await actor.set_value("RUN_SUMMARY", summary)
        await actor.fail("ECB exchange rates are unavailable; no results were produced and nothing was charged.")
        return summary
    summary["fx"] = {"source": "ECB", "date": fx_date, "eurToPln": rates.get("PLN")}

    source = source_factory(http)
    outputs: dict[str, CityOutput] = {}
    for city_key in run_input.cities:
        await actor.status(f"Fetching {CITIES[city_key].display_name}...")
        city = await fetch_city(http, source, city_key, run_input, as_of)
        city_summary = {"status": city.status, "reason": city.reason, "sides": city.sides}
        summary["cities"][city_key] = city_summary
        if city.status != "ok":
            continue
        out = compute_city(city, run_input, rates, fx_date, as_of)
        outputs[city_key] = out
        city_summary.update(gate=out.gate, groupsInfo=out.groups_info)

    area_records = [rec for out in outputs.values() for rec in out.area_records]
    scored = sort_scored([item for out in outputs.values() for item in out.scored], run_input.output_currency)

    if not area_records and not scored:
        reasons = "; ".join(f"{k}: {v['reason'] or 'no results'}" for k, v in summary["cities"].items())
        summary.update(status="failed", reason=f"No results ({reasons})", timeS=round(time.monotonic() - started, 1))
        await actor.set_value("RUN_SUMMARY", summary)
        await actor.fail(f"No results were produced and nothing was charged. {reasons}")
        return summary

    if run_input.wants_yields:
        await actor.set_value("YIELD_REPORT", {
            "fx": summary["fx"],
            "cities": {k: {"groups": out.report_groups, "gate": out.gate} for k, out in outputs.items()},
        })
    summary["status"] = "pushing"
    await actor.set_value("RUN_SUMMARY", summary)

    # Free records first so the dataset is never empty; then charged yields; scored listings arrive best deals first.
    free_area = [r for r in area_records if r["confidence"] not in CHARGED_CONFIDENCE]
    charged_area = [r for r in area_records if r["confidence"] in CHARGED_CONFIDENCE]
    scored_records = [rec for _, rec in scored]
    pushed_free, _ = await actor.push(free_area, None)
    pushed_area, area_limit = await actor.push(charged_area, AREA_YIELD_EVENT)
    pushed_scored, scored_limit = await actor.push(scored_records, SCORED_LISTING_EVENT)
    limit_reached = area_limit or scored_limit

    failed = [k for k, v in summary["cities"].items() if v["status"] != "ok"]
    summary.update(
        status="partial" if failed or limit_reached else "ok",
        chargeLimitReached=limit_reached,
        records={"areaYield": pushed_free + pushed_area, "scoredListing": pushed_scored},
        events={
            AREA_YIELD_EVENT: {"chargeable": len(charged_area), "pushed": pushed_area,
                               "charged": actor.charged_count(AREA_YIELD_EVENT)},
            SCORED_LISTING_EVENT: {"chargeable": len(scored_records), "pushed": pushed_scored,
                                   "charged": actor.charged_count(SCORED_LISTING_EVENT)},
        },
        timeS=round(time.monotonic() - started, 1),
    )
    if limit_reached:
        summary["note"] = (f"Stopped at the run's maximum charge: {pushed_area} of {len(charged_area)} yield groups "
                           f"and {pushed_scored} of {len(scored_records)} scored listings were delivered (best deals first).")
    await actor.set_value("RUN_SUMMARY", summary)
    message = f"{len(outputs)} cities, {pushed_free + pushed_area} yield groups, {pushed_scored} scored listings"
    if limit_reached:
        message = f"Stopped at your maximum charge. {message}"
    if failed:
        message += f"; skipped: {', '.join(failed)}"
    await actor.status(message)
    return summary

from __future__ import annotations

import logging
from decimal import Decimal

from apify import Actor, Event
from crawlee._log_config import configure_logger

from src.charging import DEFAULT_DATASET_ITEM_EVENT, affordable_count, push_with_charging
from src.http import PROXY_ACCESS_MESSAGE, HttpClient, ProxyAccessError
from src.inputs import RunInput
from src.monitor import STATE_STORE
from src.pipeline import run

logger = logging.getLogger(__name__)


class ApifyActorPort:
    """Adapts apify.Actor to the pipeline's ActorPort."""

    def __init__(self) -> None:
        self.summary: dict | None = None
        self.yield_report: dict | None = None

    def track(self, summary: dict, yield_report: dict | None = None) -> None:
        self.summary = summary
        if yield_report is not None:
            self.yield_report = yield_report

    def charging_info(self) -> dict:
        charging = Actor.get_charging_manager()
        max_usd = charging.get_max_total_charge_usd()  # Decimal('inf') when the run has no limit
        return {
            "isPayPerEvent": charging.get_pricing_info().is_pay_per_event,
            "maxChargeUsd": None if max_usd.is_infinite() else float(max_usd),
            "memoryMbytes": Actor.configuration.memory_mbytes,  # ACTOR_MEMORY_MBYTES; None locally
        }

    async def push(
        self, records: list[dict], event: str | None, on_pushed=None, dataset: str | None = None,
    ) -> tuple[int, bool]:
        """Push in batches; `dataset` is an alias from actor.json (None = default dataset).

        Default dataset: Actor.push_data(charged_event_name=...), which charges per pushed item.
        Aliased dataset: Dataset.push_data has no charging, so the event is charged with Actor.charge
        after the batch is stored. Both paths are capped by `capacity` first (budget check -> push -> charge).
        """
        if not records:
            return 0, False
        charging = Actor.get_charging_manager()
        aliased = await Actor.open_dataset(alias=dataset) if dataset else None

        async def pusher(batch: list[dict], charged_event: str | None) -> int:
            if aliased is not None:
                await aliased.push_data(batch)
                if charged_event is None:
                    return len(batch)
                return (await Actor.charge(event_name=charged_event, count=len(batch))).charged_count
            if charged_event is None:
                await Actor.push_data(batch)
                return len(batch)
            result = await Actor.push_data(batch, charged_event_name=charged_event)
            return result.charged_count

        return await push_with_charging(
            pusher, records, event,
            is_pay_per_event=charging.get_pricing_info().is_pay_per_event,
            capacity=lambda e: self.capacity(e, default_dataset=aliased is None),
            on_pushed=on_pushed,
        )

    def capacity(self, event: str | None, default_dataset: bool = True) -> int | None:
        """Records affordable within the run's max charge; the synthetic dataset-item price counts only for the default dataset."""
        charging = Actor.get_charging_manager()
        max_usd = charging.get_max_total_charge_usd()
        if max_usd.is_infinite():
            return None
        prices = charging.get_pricing_info().per_event_prices
        # Same rule as the SDK for events without a configured price: free on the platform, $1 in local tests.
        unknown = Decimal(0) if Actor.is_at_home() else Decimal(1)
        per_item = prices.get(DEFAULT_DATASET_ITEM_EVENT, unknown) if default_dataset else Decimal(0)
        if event is not None:
            per_item += prices.get(event, unknown)
        return affordable_count(max_usd, charging.calculate_total_charged_amount(), per_item)

    def charged_count(self, event: str) -> int | None:
        charging = Actor.get_charging_manager()
        return charging.get_charged_event_count(event) if charging.get_pricing_info().is_pay_per_event else None

    async def set_value(self, key: str, value: dict) -> None:
        await Actor.set_value(key, value)

    async def load_state(self, key: str) -> dict:
        store = await Actor.open_key_value_store(name=STATE_STORE)
        return await store.get_value(key) or {}

    async def save_state(self, key: str, state: dict) -> None:
        store = await Actor.open_key_value_store(name=STATE_STORE)
        await store.set_value(key, state)

    async def fail(self, message: str) -> None:
        await Actor.fail(status_message=message)

    async def status(self, message: str) -> None:
        await Actor.set_status_message(message)


async def make_http(run_input: RunInput) -> HttpClient:
    # Proxy access from outside Actors is disabled on the owner's account, so local runs go direct.
    if not Actor.is_at_home() or not run_input.proxy_configuration:
        return HttpClient()
    try:
        proxy = await Actor.create_proxy_configuration(actor_proxy_input=run_input.proxy_configuration)
    except Exception as e:  # e.g. a proxy group the account cannot use
        logger.warning("Proxy configuration failed (%s)", type(e).__name__)
        raise ProxyAccessError(PROXY_ACCESS_MESSAGE) from e
    if proxy is None:
        return HttpClient()

    async def proxy_url_for(session_id: str) -> str | None:
        return await proxy.new_url(session_id=session_id)

    return HttpClient(proxy_url_for=proxy_url_for)


def configure_app_logging() -> None:
    """Give our modules the Actor log handler and level.

    The SDK configures only the `apify` and `apify_client` loggers, so INFO lines from `src.*` would
    be dropped (root level WARNING) on the platform.
    """
    configure_logger(logging.getLogger("src"), remove_old_handlers=True)


async def main() -> None:
    async with Actor:
        configure_app_logging()
        port = ApifyActorPort()

        async def on_aborting(*_args: object) -> None:
            # The platform force-stops 30 s after ABORTING; keep what is known so far.
            if port.summary is not None:
                port.summary["aborted"] = True
                await Actor.set_value("RUN_SUMMARY", port.summary)
            if port.yield_report is not None:  # only groups already pushed
                await Actor.set_value("YIELD_REPORT", port.yield_report)

        Actor.on(Event.ABORTING, on_aborting)
        raw_input = await Actor.get_input() or {}
        await run(port, raw_input, http_factory=make_http)

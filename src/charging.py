from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from decimal import Decimal

# Event names exactly as entered in Apify Console (Monetization -> pay per event).
AREA_YIELD_EVENT = "area-yield"          # $0.02 per areaYield with confidence high or medium
SCORED_LISTING_EVENT = "scored-listing"  # $0.001 per scoredListing or listing (Free plan)
CHARGED_CONFIDENCE = ("high", "medium")
# Synthetic platform event charged per item written to the default dataset when it has a price
# (on by default for new PPE Actors; this Actor expects it removed in Console, but never relies on it).
DEFAULT_DATASET_ITEM_EVENT = "apify-default-dataset-item"
PUSH_BATCH = 100
# Alias of the extra dataset for areaYield records (actor.json storages.datasets). Items pushed to it never
# trigger the synthetic apify-default-dataset-item event (SDK 4.3.0: is_default_dataset is False for aliases).
YIELDS_DATASET = "yields"


async def push_with_charging(
    pusher: Callable[[list[dict], str | None], Awaitable[int]],
    records: list[dict],
    event: str | None,
    *,
    is_pay_per_event: bool,
    capacity: Callable[[str | None], int | None],
    batch_size: int = PUSH_BATCH,
    on_pushed: Callable[[list[dict]], Awaitable[None]] | None = None,
) -> tuple[int, bool]:
    """Push records in batches, charging `event` per record; returns (pushed, limit_reached)."""
    pushed = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        if not is_pay_per_event:
            await pusher(batch, None)
            pushed += len(batch)
            if on_pushed:
                await on_pushed(batch)
            continue
        cap = capacity(event)
        # With no budget left the SDK still lets one charged item through to overcharge, and the
        # platform then terminates the run; so never send a batch larger than what fits.
        if cap is not None:
            if cap <= 0:
                return pushed, True
            batch = batch[:cap]
        charged = await pusher(batch, event) if event is not None else await _push_free(pusher, batch)
        pushed += charged
        if on_pushed and charged:
            await on_pushed(batch[:charged])
        if charged < len(batch) or len(batch) < len(records[i:i + batch_size]):
            return pushed, True
    return pushed, False


def affordable_count(max_total_usd: Decimal, charged_usd: Decimal, per_item_usd: Decimal) -> int | None:
    """Items that keep the run's total charge strictly below its limit; None = no limit or free."""
    if not per_item_usd or max_total_usd.is_infinite():
        return None
    remaining = max_total_usd - charged_usd
    n = math.floor(remaining / per_item_usd)
    # Per the PPE docs the platform aborts a run once charges reach the limit, so never land on it exactly.
    if n > 0 and n * per_item_usd >= remaining:
        n -= 1
    return max(0, n)


async def _push_free(pusher: Callable[[list[dict], str | None], Awaitable[int]], batch: list[dict]) -> int:
    await pusher(batch, None)
    return len(batch)

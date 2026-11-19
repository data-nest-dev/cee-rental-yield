from __future__ import annotations

from collections.abc import Awaitable, Callable

# Event names exactly as entered in Apify Console (Monetization -> pay per event).
AREA_YIELD_EVENT = "area-yield"          # $0.02 per areaYield with confidence high or medium
SCORED_LISTING_EVENT = "scored-listing"  # $0.004 per scoredListing
CHARGED_CONFIDENCE = ("high", "medium")
# Synthetic platform event charged per item written to the default dataset when it has a price
# (on by default for new PPE Actors; this Actor expects it removed in Console, but never relies on it).
DEFAULT_DATASET_ITEM_EVENT = "apify-default-dataset-item"
PUSH_BATCH = 100


async def push_with_charging(
    pusher: Callable[[list[dict], str | None], Awaitable[int]],
    records: list[dict],
    event: str | None,
    *,
    is_pay_per_event: bool,
    capacity: Callable[[str | None], int | None],
    batch_size: int = PUSH_BATCH,
) -> tuple[int, bool]:
    """Push records in batches, charging `event` per record; returns (pushed, limit_reached)."""
    pushed = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        if not is_pay_per_event:
            await pusher(batch, None)
            pushed += len(batch)
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
        if charged < len(batch) or len(batch) < len(records[i:i + batch_size]):
            return pushed, True
    return pushed, False


async def _push_free(pusher: Callable[[list[dict], str | None], Awaitable[int]], batch: list[dict]) -> int:
    await pusher(batch, None)
    return len(batch)

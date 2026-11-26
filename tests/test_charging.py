from __future__ import annotations

import pytest

from src.charging import push_with_charging


class Recorder:
    def __init__(self, charge_ratio: float = 1.0) -> None:
        self.calls: list[tuple[int, str | None]] = []
        self.ratio = charge_ratio

    async def __call__(self, batch: list[dict], event: str | None) -> int:
        self.calls.append((len(batch), event))
        return int(len(batch) * self.ratio) if event else len(batch)


RECORDS = [{"i": i} for i in range(250)]


@pytest.mark.asyncio
async def test_not_pay_per_event_pushes_everything_without_charging() -> None:
    rec = Recorder(charge_ratio=0)  # outside PPE the SDK reports charged_count=0
    pushed, limit = await push_with_charging(rec, RECORDS, "scored-listing", is_pay_per_event=False, capacity=lambda e: 0)
    assert (pushed, limit) == (250, False)
    assert rec.calls == [(100, None), (100, None), (50, None)]


@pytest.mark.asyncio
async def test_unlimited_budget_charges_every_batch() -> None:
    rec = Recorder()
    pushed, limit = await push_with_charging(rec, RECORDS, "scored-listing", is_pay_per_event=True, capacity=lambda e: None)
    assert (pushed, limit) == (250, False)
    assert {e for _, e in rec.calls} == {"scored-listing"}


@pytest.mark.asyncio
async def test_batch_is_capped_to_what_fits_and_push_stops() -> None:
    remaining = {"scored-listing": 130}
    rec = Recorder()

    async def pusher(batch, event):
        remaining[event] -= len(batch)
        return await rec(batch, event)

    pushed, limit = await push_with_charging(pusher, RECORDS, "scored-listing", is_pay_per_event=True,
                                             capacity=lambda e: remaining[e])
    assert (pushed, limit) == (130, True)
    assert rec.calls == [(100, "scored-listing"), (30, "scored-listing")]


@pytest.mark.asyncio
async def test_zero_budget_never_sends_a_charged_push() -> None:
    rec = Recorder()
    pushed, limit = await push_with_charging(rec, RECORDS, "area-yield", is_pay_per_event=True, capacity=lambda e: 0)
    assert (pushed, limit) == (0, True)
    assert rec.calls == []


@pytest.mark.asyncio
async def test_free_records_are_unlimited_when_dataset_items_cost_nothing() -> None:
    rec = Recorder()
    caps = {None: None, "area-yield": 0}
    pushed, limit = await push_with_charging(rec, RECORDS[:5], None, is_pay_per_event=True, capacity=caps.get)
    assert (pushed, limit) == (5, False)
    assert rec.calls == [(5, None)]


@pytest.mark.asyncio
async def test_free_records_are_capped_when_the_synthetic_dataset_item_event_has_a_price() -> None:
    rec = Recorder()
    pushed, limit = await push_with_charging(rec, RECORDS[:5], None, is_pay_per_event=True, capacity=lambda e: 2)
    assert (pushed, limit) == (2, True)
    assert rec.calls == [(2, None)]


@pytest.mark.asyncio
async def test_sdk_charging_fewer_than_sent_counts_as_limit() -> None:
    rec = Recorder(charge_ratio=0.5)
    pushed, limit = await push_with_charging(rec, RECORDS, "scored-listing", is_pay_per_event=True, capacity=lambda e: None)
    assert (pushed, limit) == (50, True)


from decimal import Decimal

from src.charging import affordable_count


@pytest.mark.parametrize("max_usd, charged, price, expected", [
    ("0.01", "0.00005", "0.001", 9),       # 9 x 0.001 = 0.009 < 0.00995 remaining
    ("0.02", "0", "0.02", 0),              # one item would land exactly on the limit -> not allowed
    ("0.04", "0", "0.02", 1),              # two would reach it; one stays below
    ("0.05", "0", "0.02", 2),
    ("0.01", "0.02", "0.001", 0),          # already over
])
def test_affordable_count_stays_strictly_below_the_limit(max_usd, charged, price, expected) -> None:
    assert affordable_count(Decimal(max_usd), Decimal(charged), Decimal(price)) == expected


def test_affordable_count_unlimited_or_free() -> None:
    assert affordable_count(Decimal("inf"), Decimal(0), Decimal("0.001")) is None
    assert affordable_count(Decimal("0.01"), Decimal(0), Decimal(0)) is None

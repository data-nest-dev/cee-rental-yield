from __future__ import annotations

from datetime import date

from src.monitor import compute_changes, update_state


def test_new_price_cut_and_unchanged() -> None:
    state = {"a": {"lastPriceLocal": 100_000}, "b": {"lastPriceLocal": 100_000}, "c": {"lastPriceLocal": 100_000}}
    listings = {"a": {"price_local": 99_000}, "b": {"price_local": 99_100}, "c": {"price_local": 101_000},
                "d": {"price_local": 50_000}}
    changes = compute_changes(listings, state)
    assert changes == {
        "a": {"change_type": "priceCut", "price_cut_pct": 1.0},   # exactly 1% counts
        "d": {"change_type": "new", "price_cut_pct": None},
    }  # b: 0.9% cut, c: price rise -> unchanged


def test_update_state_keeps_first_seen_and_prunes_stale_entries() -> None:
    today = date(2026, 11, 18)
    state = {
        "kept": {"firstSeenAt": "2026-10-01", "lastSeenAt": "2026-10-20", "lastPriceLocal": 1},
        "stale": {"firstSeenAt": "2026-08-01", "lastSeenAt": "2026-09-18", "lastPriceLocal": 1},
        "seen": {"firstSeenAt": "2026-07-01", "lastSeenAt": "2026-07-02", "lastPriceLocal": 5},
    }
    new = update_state(state, {"seen": {"price_local": 4}, "fresh": {"price_local": 9}}, today)
    assert set(new) == {"kept", "seen", "fresh"}       # stale: 61 days unseen
    assert new["seen"] == {"firstSeenAt": "2026-07-01", "lastSeenAt": "2026-11-18", "lastPriceLocal": 4}
    assert new["fresh"]["firstSeenAt"] == "2026-11-18"
    assert state["seen"]["lastPriceLocal"] == 5      # input not mutated

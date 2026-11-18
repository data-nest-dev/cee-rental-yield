from __future__ import annotations

from datetime import date


def compute_changes(
    listings_by_key: dict[str, dict],
    state: dict[str, dict],
) -> dict[str, dict]:
    changes: dict[str, dict] = {}

    for dedup_key, info in listings_by_key.items():
        price = info["price_local"]
        prev = state.get(dedup_key)

        if prev is None:
            changes[dedup_key] = {
                "change_type": "new",
                "price_cut_pct": None,
            }
        else:
            prev_price = prev.get("lastPriceLocal", price)
            if prev_price > 0 and (prev_price - price) / prev_price >= 0.01:
                cut_pct = round((prev_price - price) / prev_price * 100, 2)
                changes[dedup_key] = {
                    "change_type": "priceCut",
                    "price_cut_pct": cut_pct,
                }
            # unchanged → not included

    return changes


def update_state(
    state: dict[str, dict],
    listings_by_key: dict[str, dict],
) -> dict[str, dict]:
    today = date.today().isoformat()
    new_state = dict(state)

    for dedup_key, info in listings_by_key.items():
        if dedup_key in new_state:
            new_state[dedup_key]["lastPriceLocal"] = info["price_local"]
        else:
            new_state[dedup_key] = {
                "firstSeenAt": today,
                "lastPriceLocal": info["price_local"],
            }

    return new_state

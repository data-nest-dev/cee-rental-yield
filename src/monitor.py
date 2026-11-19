from __future__ import annotations

from datetime import date, timedelta

STATE_STORE = "cee-rental-yield-state"
PRICE_CUT_THRESHOLD = 0.01
PRUNE_AFTER_DAYS = 60


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
            if prev_price > 0 and (prev_price - price) / prev_price >= PRICE_CUT_THRESHOLD:
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
    today: date | None = None,
    prune_after_days: int = PRUNE_AFTER_DAYS,
) -> dict[str, dict]:
    today = today or date.today()
    iso = today.isoformat()
    new_state = {k: dict(v) for k, v in state.items()}

    for dedup_key, info in listings_by_key.items():
        entry = new_state.setdefault(dedup_key, {"firstSeenAt": iso})
        entry["lastPriceLocal"] = info["price_local"]
        entry["lastSeenAt"] = iso

    cutoff = (today - timedelta(days=prune_after_days)).isoformat()
    return {
        k: v for k, v in new_state.items()
        if (v.get("lastSeenAt") or v.get("firstSeenAt") or iso) >= cutoff
    }

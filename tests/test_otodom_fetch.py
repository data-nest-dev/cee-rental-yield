from __future__ import annotations

import json

import pytest

from src.sources.otodom import OtodomSource, _district_id

CITY = "slaskie/katowice/katowice/katowice"


def _item(slug: str, district: str, estate: str = "FLAT") -> dict:
    return {
        "slug": slug,
        "estate": estate,
        "href": f"[lang]/ad/{slug}",
        "location": {"reverseGeocoding": {"locations": [
            {"id": CITY, "locationLevel": "city_or_village"},
            {"id": f"{CITY}/{district}", "locationLevel": "district"},
        ]}},
    }


def _html(build_id: str, items: list[dict], total_pages: int) -> str:
    data = {"buildId": build_id, "props": {"pageProps": {"data": {"searchAds": {
        "items": items, "pagination": {"totalPages": total_pages},
    }}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def _json(items: list[dict], total_pages: int) -> str:
    return json.dumps({"pageProps": {"data": {"searchAds": {
        "items": items, "pagination": {"totalPages": total_pages},
    }}}})


class FakeHttp:
    def __init__(self, routes: dict[str, list[tuple[int, str]]]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    async def get(self, url: str, headers: dict | None = None) -> tuple[int, str]:
        self.calls.append(url)
        for key, responses in self.routes.items():
            if key in url:
                return responses.pop(0) if len(responses) > 1 else responses[0]
        return 404, ""


def _district_page(district: str, page: int) -> str:
    return f"/mieszkanie/{CITY}/{district}.json?page={page}&"


@pytest.mark.asyncio
async def test_per_district_tops_up_each_district_to_quota() -> None:
    page1 = [_item("a1", "bogucice"), _item("b1", "dab")]
    http = FakeHttp({
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [(200, _html("B1", page1, 1))],
        _district_page("bogucice", 1): [(200, _json(
            [_item("a1", "bogucice"), _item("a2", "bogucice"), _item("a3", "bogucice")], 5,
        ))],
        _district_page("dab", 1): [(200, _json([_item("b2", "dab")], 1))],
    })
    items, stats = await OtodomSource(http).fetch_listings(
        "katowice", "sale", 1500, max_per_district=3,
    )

    slugs = [it["slug"] for it in items]
    assert sorted(slugs) == ["a1", "a2", "a3", "b1", "b2"]
    assert stats["districts"] == 2
    # bogucice reached its quota on page 1, so page 2 is never requested
    assert not any(_district_page("bogucice", 2) in c for c in http.calls)
    assert stats["district_pages"] == 2


@pytest.mark.asyncio
async def test_non_flats_do_not_count_toward_district_quota() -> None:
    page1 = [_item("a1", "bogucice")]
    http = FakeHttp({
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [(200, _html("B1", page1, 1))],
        _district_page("bogucice", 1): [(200, _json(
            [_item("i1", "bogucice", estate="INVESTMENT"), _item("a2", "bogucice")], 2,
        ))],
        _district_page("bogucice", 2): [(200, _json([_item("a3", "bogucice")], 2))],
    })
    items, _ = await OtodomSource(http).fetch_listings(
        "katowice", "sale", 1500, max_per_district=3,
    )
    assert {"a1", "a2", "a3", "i1"} == {it["slug"] for it in items}


@pytest.mark.asyncio
async def test_build_id_refresh_retries_with_new_id() -> None:
    page1 = [_item("a1", "bogucice")]
    http = FakeHttp({
        "/_next/data/OLD/": [(404, "")],
        "/_next/data/NEW/": [(200, _json([_item("a2", "bogucice")], 2))],
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [
            (200, _html("OLD", page1, 2)),
            (200, _html("NEW", page1, 2)),
        ],
    })
    items, stats = await OtodomSource(http).fetch_listings("katowice", "sale", 1500)

    assert stats["build_id_refreshes"] == 1
    assert stats["fallback_to_html"] is False
    assert any("/_next/data/NEW/" in c for c in http.calls)
    assert {"a1", "a2"} == {it["slug"] for it in items}


def test_district_id_ignores_other_cities() -> None:
    raw = _item("x", "bogucice")
    assert _district_id(raw, CITY) == f"{CITY}/bogucice"
    assert _district_id(raw, "mazowieckie/warszawa/warszawa/warszawa") is None

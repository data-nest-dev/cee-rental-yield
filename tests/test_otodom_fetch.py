from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.sources.otodom import OtodomSource, _district_id, district_paths

FIXTURE_DIR = Path(__file__).parent / "fixtures"
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


def _html(
    build_id: str,
    items: list[dict],
    total_pages: int,
    districts: list[str] | None = None,
    sorting: tuple[str, str, int] = ("LATEST", "DESC", 72),
    total_items: int | None = None,
    market: str | None = None,
) -> str:
    by, direction, per_page = sorting
    pagination = {"totalPages": total_pages, "itemsPerPage": per_page}
    if total_items is not None:
        pagination["totalItems"] = total_items
    page_data: dict = {"searchAds": {"items": items, "pagination": pagination}}
    if districts is not None:
        page_data["searchLinksRelatedLocations"] = {"items": [
            {"name": d, "location": f"{CITY}/{d}"} for d in districts
        ]}
    data = {"buildId": build_id, "props": {"pageProps": {
        "data": page_data, "sortingOption": {"by": by, "direction": direction},
        **({"filteringQueryParams": {"market": market}} if market else {}),
    }}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def _json(items: list[dict], total_pages: int, total_items: int | None = None) -> str:
    pagination: dict = {"totalPages": total_pages, "itemsPerPage": 72}
    if total_items is not None:
        pagination["totalItems"] = total_items
    return json.dumps({"pageProps": {"data": {"searchAds": {
        "items": items, "pagination": pagination,
    }}}})


class FakeHttp:
    def __init__(self, routes: dict[str, list[tuple[int, str]]]) -> None:
        self.routes = routes
        self.calls: list[str] = []
        self.windows: list[tuple[str, str]] = []

    def start_window(self, domain: str, label: str) -> None:
        self.windows.append((domain, label))

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
    assert stats["district_source"] == "discovery"
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


@pytest.mark.asyncio
async def test_district_list_replaces_discovery_pages() -> None:
    # City has 50 pages, but with the district list only page 1 is fetched city-wide,
    # and a district absent from page 1 (zarzecze) is still paged.
    page1 = [_item("a1", "bogucice")]
    http = FakeHttp({
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [
            (200, _html("B1", page1, 50, districts=["bogucice", "zarzecze"])),
        ],
        _district_page("bogucice", 1): [(200, _json([_item("a2", "bogucice")], 1))],
        _district_page("zarzecze", 1): [(200, _json([_item("z1", "zarzecze")], 1))],
    })
    items, stats = await OtodomSource(http).fetch_listings(
        "katowice", "sale", 1500, max_per_district=5,
    )

    assert stats["district_source"] == "related_locations"
    assert stats["districts"] == 2
    city_pages = [c for c in http.calls if f"/mieszkanie/{CITY}.json" in c]
    assert city_pages == []
    assert {"a1", "a2", "z1"} == {it["slug"] for it in items}


def test_district_paths_from_fixture() -> None:
    data = json.loads((FIXTURE_DIR / "otodom_rent_katowice.json").read_text())
    paths = district_paths(data["pageProps"], CITY)
    assert len(paths) == 22
    assert f"{CITY}/bogucice" in paths
    assert all(p.startswith(CITY + "/") for p in paths)


def test_district_paths_missing_or_foreign() -> None:
    assert district_paths({"data": {}}, CITY) == []
    foreign = {"data": {"searchLinksRelatedLocations": {"items": [
        {"name": "Mokotów", "location": "mazowieckie/warszawa/warszawa/warszawa/mokotow"},
    ]}}}
    assert district_paths(foreign, CITY) == []


@pytest.mark.asyncio
async def test_requests_use_latest_sort_and_72_per_page() -> None:
    page1 = [_item(f"a{i}", "bogucice") for i in range(72)]
    page2 = [_item(f"b{i}", "bogucice") for i in range(72)]
    http = FakeHttp({
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [(200, _html("B1", page1, 2))],
        "/_next/data/B1/": [(200, _json(page2, 2))],
    })
    items, stats = await OtodomSource(http).fetch_listings("katowice", "sale", 1500)

    assert len(items) == 144
    assert stats["pages_fetched"] == 2
    assert stats["page1_refetched"] is False
    for url in http.calls:
        assert "by=LATEST" in url and "direction=DESC" in url and "limit=72" in url


@pytest.mark.asyncio
async def test_page_count_follows_pagination_at_72_per_page() -> None:
    # 150 listings at 72 per page -> 3 pages; budget of 1500 does not stop early
    pages = [[_item(f"p{n}-{i}", "bogucice") for i in range(k)] for n, k in ((1, 72), (2, 72), (3, 6))]
    http = FakeHttp({
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [(200, _html("B1", pages[0], 3))],
        "page=2&": [(200, _json(pages[1], 3))],
        "page=3&": [(200, _json(pages[2], 3))],
    })
    items, stats = await OtodomSource(http).fetch_listings("katowice", "sale", 1500)
    assert len(items) == 150
    assert stats["pages_fetched"] == 3


@pytest.mark.asyncio
async def test_page1_refetched_when_html_ignores_sort() -> None:
    html_items = [_item("default1", "bogucice")]
    json_items = [_item("latest1", "bogucice"), _item("latest2", "bogucice")]
    http = FakeHttp({
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [
            (200, _html("B1", html_items, 1, sorting=("DEFAULT", "DESC", 36))),
        ],
        "/_next/data/B1/": [(200, _json(json_items, 1))],
    })
    items, stats = await OtodomSource(http).fetch_listings("katowice", "sale", 1500)
    assert stats["page1_refetched"] is True
    assert [it["slug"] for it in items] == ["latest1", "latest2"]


def test_sort_and_page_size_configurable_in_code() -> None:
    src = OtodomSource(FakeHttp({}), sort_by="DEFAULT", page_limit=36)
    src._build_id = "B"
    url = src._next_data_url(CITY, "sprzedaz", 2)
    assert "by=DEFAULT" in url and "limit=36" in url and "page=2" in url


@pytest.mark.asyncio
async def test_records_totals_and_fetched_counts_per_district() -> None:
    page1 = [_item("a1", "bogucice")]
    http = FakeHttp({
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [
            (200, _html("B1", page1, 9, districts=["bogucice", "dab"], total_items=600)),
        ],
        _district_page("bogucice", 1): [(200, _json([_item("a1", "bogucice"), _item("a2", "bogucice")], 1, total_items=2))],
        _district_page("dab", 1): [(200, _json([_item("d1", "dab"), _item("a3", "bogucice")], 1, total_items=40))],
    })
    _, stats = await OtodomSource(http).fetch_listings("katowice", "sale", 1500, max_per_district=300)

    assert stats["total_items"] == 600
    assert stats["fetched_items"] == 4
    assert stats["district_total_items"] == {"bogucice": 2, "dab": 40}
    # a3 came from the dab page but is geocoded to bogucice
    assert stats["fetched_by_district"] == {"bogucice": 3, "dab": 1}


@pytest.mark.asyncio
async def test_city_wide_mode_records_city_total_only() -> None:
    http = FakeHttp({
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [
            (200, _html("B1", [_item("a1", "bogucice"), _item("b1", "dab")], 1, total_items=2)),
        ],
    })
    _, stats = await OtodomSource(http).fetch_listings("katowice", "sale", 1500)
    assert stats["total_items"] == 2
    assert stats["fetched_by_district"] == {"bogucice": 1, "dab": 1}
    assert "district_total_items" not in stats


@pytest.mark.asyncio
async def test_html_fallback_returns_to_json_when_build_id_changes() -> None:
    # Deploy in progress: OLD 404s, the refresh still sees OLD, the next HTML page shows NEW.
    http = FakeHttp({
        "/_next/data/OLD/": [(404, "")],
        "/_next/data/NEW/": [(200, _json([_item("c1", "bogucice")], 3))],
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [
            (200, _html("OLD", [_item("a1", "bogucice")], 3)),   # page 1
            (200, _html("OLD", [], 3)),                           # refresh: still old
            (200, _html("NEW", [_item("b1", "bogucice")], 3)),   # page 2 via HTML
        ],
    })
    items, stats = await OtodomSource(http).fetch_listings("katowice", "sale", 1500)

    assert [it["slug"] for it in items] == ["a1", "b1", "c1"]
    assert stats["fallback_to_html"] is True
    assert stats["html_pages"] == 1
    assert stats["fallback_recoveries"] == 1
    assert any("/_next/data/NEW/" in c and "page=3&" in c for c in http.calls)


@pytest.mark.asyncio
async def test_zero_quota_means_automatic_quota() -> None:
    # 2 districts -> max(150, ceil(1500 / 2)) = 750 per district
    http = FakeHttp({
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [
            (200, _html("B1", [_item("a1", "bogucice")], 1, districts=["bogucice", "dab"])),
        ],
        _district_page("bogucice", 1): [(200, _json([_item("a2", "bogucice")], 1))],
        _district_page("dab", 1): [(200, _json([_item("d1", "dab")], 1))],
    })
    _, stats = await OtodomSource(http).fetch_listings("katowice", "sale", 1500, max_per_district=0)
    assert stats["quota_per_district"] == 750


def test_market_param_in_urls_for_all_and_secondary() -> None:
    for market in ("ALL", "SECONDARY"):
        src = OtodomSource(FakeHttp({}), market=market)
        src._build_id = "B"
        assert f"market={market}" in src._next_data_url(CITY, "sprzedaz", 1)
        assert f"market={market}" in "&".join(src._order_params())
    assert OtodomSource(FakeHttp({})).market == "ALL"


@pytest.mark.asyncio
async def test_secondary_market_sent_on_first_page_and_district_requests() -> None:
    page1 = [_item("a1", "bogucice")]
    http = FakeHttp({
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [
            (200, _html("B1", page1, 1, districts=["bogucice"], market="SECONDARY")),
        ],
        _district_page("bogucice", 1): [(200, _json(page1, 1))],
    })
    await OtodomSource(http, market="SECONDARY").fetch_listings("katowice", "sale", 1500, max_per_district=3)
    assert http.calls and all("market=SECONDARY" in c for c in http.calls)
    assert not any("market=ALL" in c for c in http.calls)


@pytest.mark.asyncio
async def test_first_page_with_wrong_echoed_market_is_refetched_from_next_data() -> None:
    """If the portal ignored the market filter on the HTML page, page 1 must not be reused."""
    ignored = [_item("wrong", "bogucice")]
    http = FakeHttp({
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [
            (200, _html("B1", ignored, 1, market="ALL")),
        ],
        "/_next/data/B1/": [(200, _json([_item("right", "bogucice")], 1))],
    })
    items, _ = await OtodomSource(http, market="SECONDARY").fetch_listings("katowice", "sale", 1500)
    assert [it["slug"] for it in items] == ["right"]


@pytest.mark.asyncio
async def test_logs_start_and_progress(caplog) -> None:
    import logging
    page1 = [_item("a1", "bogucice")]
    routes = {f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{CITY}": [(200, _html("B1", page1, 60))]}
    for n in range(2, 61):
        routes[f"page={n}&"] = [(200, _json([_item(f"x{n}", "bogucice")], 60))]
    with caplog.at_level(logging.INFO, logger="src.sources.otodom"):
        await OtodomSource(FakeHttp(routes)).fetch_listings("katowice", "sale", 100000)
    msgs = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("Fetching katowice sale") for m in msgs)
    assert len([m for m in msgs if m.startswith("Progress katowice sale")]) == 2

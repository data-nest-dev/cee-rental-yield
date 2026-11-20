from __future__ import annotations

import json
from urllib.parse import parse_qsl, urlencode, urlsplit
import logging
import re
from datetime import date, datetime

from src.location import address_city_differs, names_other_city
from src.flags import FLAG_AUCTION, FLAG_NEEDS_RENOVATION, FLAG_SHARE, classify_title
from src.config import (
    CITIES,
    MARKET_ALL,
    MARKET_SECONDARY,
    OTODOM_TRANSACTION_MAP,
    CityConfig,
    auto_district_quota,
)
from src.http import HttpClient
from src.models import Listing

logger = logging.getLogger(__name__)
PROGRESS_EVERY = 25

# Pagination stops after this many pages in a row that add no new unique listing (page parameter ignored,
# repeated or empty pages), whatever the cause.
MAX_STALE_PAGES = 2

ROOMS_MAP = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
    "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10,
}

FLOOR_MAP = {
    "GROUND": 0, "CELLAR": -1, "GARRET": None,
    "FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5,
    "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8, "NINTH": 9, "TENTH": 10,
    "ABOVE_TENTH": None,
}

DOMAIN = "www.otodom.pl"
BASE_URL = f"https://{DOMAIN}"
# LATEST orders by first publication: stable pagination, unlike DEFAULT (ordered by paid bumps).
SORT_BY = "LATEST"
SORT_DIRECTION = "DESC"
# 72 is the largest page size Otodom honours; larger values silently fall back to 36.
PAGE_LIMIT = 72
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


class OtodomSource:
    def __init__(
        self,
        http: HttpClient,
        sort_by: str = SORT_BY,
        direction: str = SORT_DIRECTION,
        page_limit: int = PAGE_LIMIT,
        market: str = MARKET_ALL,
    ) -> None:
        self._http = http
        self._build_id: str | None = None
        self._html_mode = False
        self.sort_by = sort_by
        self.direction = direction
        self.page_limit = page_limit
        self.market = market
        self._page_calls = 0
        self._redirects: dict[str, str] = {}  # location -> redirect target learned in this fetch

    async def fetch_listings(
        self,
        city_key: str,
        transaction: str,
        max_listings: int,
        max_per_district: int | None = None,
        discovery_pages: int = 10,
    ) -> tuple[list[dict], dict]:
        cfg = CITIES[city_key]
        tx = OTODOM_TRANSACTION_MAP[transaction]
        self._http.start_window(DOMAIN, f"{city_key} {transaction}")
        self._page_calls = 0
        self._redirects = {}
        logger.info(
            "Fetching %s %s (market=%s, sampling=%s)", city_key, transaction, self.market,
            "city" if max_per_district is None else "perDistrict",
        )
        stats = {
            "pages_fetched": 0,
            "raw_items": 0,
            "build_id_refreshes": 0,
            "fallback_to_html": False,
            "city_key": city_key,
            "tx": transaction,
        }

        page1_items, pagination, build_id, district_names, ordered = await self._fetch_first_page(cfg, tx)
        district_list = list(district_names)
        self._build_id = build_id
        stats["pages_fetched"] = 1
        stats["page1_refetched"] = False
        if not ordered:
            # The HTML page ignored our sort or page size; take page 1 from the JSON route instead.
            page1_items, pagination = await self._fetch_page(cfg.location_path, tx, 1, stats)
            stats["pages_fetched"] += 1
            stats["page1_refetched"] = True
        stats["raw_items"] = len(page1_items)
        stats["total_items"] = pagination.get("totalItems")
        all_items = list(page1_items)

        city_page_limit = pagination.get("totalPages", 1)
        if max_per_district is not None:
            # The district list makes city-wide discovery pages unnecessary.
            city_page_limit = 1 if district_list else min(city_page_limit, discovery_pages)
            budget = None
        else:
            budget = max_listings

        seen_city = {it.get("slug") for it in all_items if it.get("slug")}
        stale_pages = 0
        stats["stopped_reason"] = "last_page"
        for page_num in range(2, city_page_limit + 1):
            if budget is not None and len(seen_city) >= budget:
                stats["stopped_reason"] = "quota_reached"
                break
            page_items, _ = await self._fetch_page(cfg.location_path, tx, page_num, stats)
            all_items.extend(page_items)
            stats["pages_fetched"] += 1
            stats["raw_items"] += len(page_items)
            new = {it.get("slug") for it in page_items if it.get("slug")} - seen_city
            seen_city |= new
            stale_pages = 0 if new else stale_pages + 1
            if stale_pages >= MAX_STALE_PAGES:
                stats["stopped_reason"] = "no_new_items"
                logger.warning("Stopping %s %s pagination at page %d: %d pages in a row without a new listing",
                               city_key, transaction, page_num, MAX_STALE_PAGES)
                break

        if max_per_district is None:
            _record_fetched(all_items, cfg.location_path, stats)
            return all_items, stats

        seen = {it.get("slug") for it in all_items if it.get("slug")}
        counts: dict[str, int] = {}
        for it in all_items:
            d = _district_id(it, cfg.location_path)
            if d and _is_candidate(it):
                counts[d] = counts.get(d, 0) + 1
        district_total_items: dict[str, int] = {}
        if district_list:
            districts = district_list
            stats["district_source"] = "related_locations"
        else:
            districts = sorted(counts)
            stats["district_source"] = "discovery"
        stats["districts"] = len(districts)
        stats["district_pages"] = 0
        if max_per_district == 0:
            max_per_district = auto_district_quota(len(districts))
        stats["quota_per_district"] = max_per_district

        for district in districts:
            page_num = 1
            total_pages = 1
            stale_pages = 0
            while counts.get(district, 0) < max_per_district and page_num <= total_pages:
                page_items, pag = await self._fetch_page(district, tx, page_num, stats)
                stats["pages_fetched"] += 1
                stats["district_pages"] += 1
                stats["raw_items"] += len(page_items)
                total_pages = pag.get("totalPages", 0) if pag else 0
                if page_num == 1 and pag and pag.get("totalItems") is not None:
                    district_total_items[district] = pag["totalItems"]
                added = 0
                for it in page_items:
                    slug = it.get("slug")
                    if not slug or slug in seen:
                        continue
                    seen.add(slug)
                    added += 1
                    all_items.append(it)
                    d = _district_id(it, cfg.location_path)
                    if d and _is_candidate(it):
                        counts[d] = counts.get(d, 0) + 1
                page_num += 1
                stale_pages = 0 if added else stale_pages + 1
                if stale_pages >= MAX_STALE_PAGES:
                    stats["stopped_reason"] = "no_new_items"
                    break

        names = dict(district_names or {})
        for it in all_items:
            d = _district(it, cfg.location_path)
            if d:
                names.setdefault(d[0], d[1])
        stats["district_total_items"] = {
            names.get(path, path.rsplit("/", 1)[-1]): n for path, n in district_total_items.items()
        }
        _record_fetched(all_items, cfg.location_path, stats)
        return all_items, stats

    def _order_params(self) -> list[str]:
        return [
            f"limit={self.page_limit}", f"by={self.sort_by}", f"direction={self.direction}",
            f"market={self.market}",
        ]

    def _is_ordered(self, page_props: dict) -> bool:
        sorting = page_props.get("sortingOption") or {}
        per_page = page_props.get("data", {}).get("searchAds", {}).get("pagination", {}).get("itemsPerPage")
        echoed_market = (page_props.get("filteringQueryParams") or {}).get("market")
        return (
            echoed_market in (None, self.market)
            and sorting.get("by") == self.sort_by
            and sorting.get("direction") == self.direction
            and per_page == self.page_limit
        )

    async def _fetch_first_page(
        self, cfg: CityConfig, tx: str,
    ) -> tuple[list[dict], dict, str, dict[str, str], bool]:
        url = (
            f"{BASE_URL}/pl/wyniki/{tx}/mieszkanie/{cfg.location_path}?"
            + "&".join(self._order_params())
        )
        headers = {"User-Agent": USER_AGENT}
        status, body = await self._http.get(url, headers=headers)

        if status != 200:
            raise RuntimeError(f"Otodom first page returned {status}")

        build_id = _extract_build_id(body)
        page_props = _page_props_from_html(body)
        search_ads = page_props.get("data", {}).get("searchAds", {})
        return (
            search_ads.get("items", []),
            search_ads.get("pagination", {}),
            build_id,
            district_links(page_props, cfg.location_path),
            self._is_ordered(page_props),
        )

    async def _fetch_page(
        self, location_path: str, tx: str, page: int, stats: dict,
    ) -> tuple[list[dict], dict]:
        result = await self._fetch_page_inner(location_path, tx, page, stats)
        self._page_calls += 1
        if self._page_calls % PROGRESS_EVERY == 0:
            window_of = getattr(self._http, "window", None)
            window = window_of(DOMAIN) if window_of else None
            logger.info(
                "Progress %s %s: %d pages fetched%s", stats.get("city_key", ""), stats.get("tx", ""),
                self._page_calls, f", {window.blocked} blocked of {window.requests} requests" if window else "",
            )
        return result

    async def _fetch_page_inner(
        self, location_path: str, tx: str, page: int, stats: dict,
    ) -> tuple[list[dict], dict]:
        if self._build_id and not self._html_mode:
            search_ads = await self._fetch_next_data_page(location_path, tx, page, stats)
            if search_ads is not None:
                return search_ads.get("items", []), search_ads.get("pagination", {})
            self._html_mode = True

        stats["fallback_to_html"] = True
        stats["html_pages"] = stats.get("html_pages", 0) + 1
        items, pagination, page_build_id = await self._fetch_html_page(location_path, tx, page)
        # During an Otodom deploy the refresh can still see the old buildId; once an HTML page
        # carries a different one, return to the (3-4x smaller) JSON route.
        if page_build_id and page_build_id != self._build_id:
            self._build_id = page_build_id
            self._html_mode = False
            stats["fallback_recoveries"] = stats.get("fallback_recoveries", 0) + 1
        return items, pagination

    def _next_data_url(self, location_path: str, tx: str, page: int) -> str:
        # curl_cffi can't send repeated params from a dict; build the query by hand
        param_parts = [f"page={page}"] + self._order_params() + [
            "ownerTypeSingleSelect=ALL", "distanceRadius=0",
        ]
        for sc in [tx, "mieszkanie"] + location_path.split("/"):
            param_parts.append(f"searchingCriteria={sc}")
        return (
            f"{BASE_URL}/_next/data/{self._build_id}/pl/wyniki/{tx}"
            f"/mieszkanie/{location_path}.json?" + "&".join(param_parts)
        )

    async def _fetch_next_data_page(
        self, location_path: str, tx: str, page: int, stats: dict,
    ) -> dict | None:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "x-nextjs-data": "1",
            "Referer": f"{BASE_URL}/pl/wyniki/{tx}/mieszkanie/{location_path}",
        }
        status, body = await self._http.get(self._data_url(location_path, tx, page), headers=headers)

        if status == 404:
            stats["build_id_refreshes"] += 1
            new_build_id = await self._refresh_build_id(location_path, tx)
            if not new_build_id or new_build_id == self._build_id:
                return None
            self._build_id = new_build_id
            status, body = await self._http.get(self._data_url(location_path, tx, page), headers=headers)

        if status != 200:
            return None

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None
        page_props = data.get("pageProps", {})
        target = page_props.get("__N_REDIRECT")
        if target and location_path in self._redirects:
            self._redirects.pop(location_path)  # the learned canonical path no longer works: HTML fallback
            return None
        if target:
            # Next.js answers 200 with a redirect marker instead of data, e.g. SECONDARY lives under
            # /mieszkanie,rynek-wtorny/. Follow it once (no loops); anything else falls back to HTML.
            redirected = self._redirect_data_url(target, page)
            if redirected is None:
                return None
            logger.info("Otodom data route redirected (page %d): following once to %s", page, redirected.split("?")[0])
            status, body = await self._http.get(redirected, headers=headers)
            if status != 200:
                return None
            try:
                page_props = json.loads(body).get("pageProps", {})
            except json.JSONDecodeError:
                return None
            if "__N_REDIRECT" in page_props:
                return None
            self._redirects[location_path] = target  # later pages of this location go straight to it
        return page_props.get("data", {}).get("searchAds", {})

    def _data_url(self, location_path: str, tx: str, page: int) -> str:
        """Canonical data URL once a redirect was learned for this location in this fetch, else the plain one."""
        target = self._redirects.get(location_path)
        learned = self._redirect_data_url(target, page) if target else None
        return learned or self._next_data_url(location_path, tx, page)

    def _redirect_data_url(self, target: str, page: int) -> str | None:
        """_next/data URL for a redirect target (a site path with its own query), with our page number."""
        parts = urlsplit(target)
        if not parts.path.startswith("/pl/wyniki/") or parts.netloc:
            return None
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "page"]
        query.insert(0, ("page", str(page)))
        return f"{BASE_URL}/_next/data/{self._build_id}{parts.path}.json?{urlencode(query)}"

    async def _fetch_html_page(
        self, location_path: str, tx: str, page: int,
    ) -> tuple[list[dict], dict, str | None]:
        url = (
            f"{BASE_URL}/pl/wyniki/{tx}/mieszkanie/{location_path}?page={page}&"
            + "&".join(self._order_params())
        )
        headers = {"User-Agent": USER_AGENT}
        status, body = await self._http.get(url, headers=headers)
        if status != 200:
            logger.warning("Otodom HTML page %d returned %d", page, status)
            return [], {}, None
        search_ads = _page_props_from_html(body).get("data", {}).get("searchAds", {})
        try:
            build_id = _extract_build_id(body)
        except ValueError:
            build_id = None
        return search_ads.get("items", []), search_ads.get("pagination", {}), build_id

    async def _refresh_build_id(self, location_path: str, tx: str) -> str | None:
        url = f"{BASE_URL}/pl/wyniki/{tx}/mieszkanie/{location_path}"
        headers = {"User-Agent": USER_AGENT}
        status, body = await self._http.get(url, headers=headers)
        if status != 200:
            return None
        try:
            return _extract_build_id(body)
        except ValueError:
            return None


def _page_props_from_html(html: str) -> dict:
    next_data = _extract_next_data(html)
    return next_data.get("props", {}).get("pageProps", next_data.get("pageProps", {}))


def district_links(page_props: dict, city_location_path: str) -> dict[str, str]:
    """District path -> name from pageProps.data.searchLinksRelatedLocations; {} if absent."""
    links = (page_props.get("data", {}).get("searchLinksRelatedLocations") or {}).get("items") or []
    result: dict[str, str] = {}
    for link in links:
        loc = link.get("location") or ""
        if loc.startswith(city_location_path + "/") and loc not in result:
            result[loc] = link.get("name") or loc.rsplit("/", 1)[-1]
    return result


def district_paths(page_props: dict, city_location_path: str) -> list[str]:
    return list(district_links(page_props, city_location_path))


def _record_fetched(items: list[dict], city_location_path: str, stats: dict) -> None:
    """Unique fetched items, overall and per geocoded district name, for sample-share reporting."""
    seen: set[str] = set()
    by_district: dict[str, int] = {}
    for it in items:
        slug = it.get("slug")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        d = _district(it, city_location_path)
        if d:
            by_district[d[1]] = by_district.get(d[1], 0) + 1
    stats["fetched_items"] = len(seen)
    stats["fetched_by_district"] = by_district


def _district(raw: dict, city_location_path: str) -> tuple[str, str] | None:
    for loc in raw.get("location", {}).get("reverseGeocoding", {}).get("locations", []):
        loc_id = loc.get("id", "")
        if loc.get("locationLevel") == "district" and loc_id.startswith(city_location_path + "/"):
            return loc_id, loc.get("name") or loc_id.rsplit("/", 1)[-1]
    return None


def _district_id(raw: dict, city_location_path: str) -> str | None:
    d = _district(raw, city_location_path)
    return d[0] if d else None


def _is_candidate(raw: dict) -> bool:
    href = raw.get("href", "")
    return raw.get("estate") == "FLAT" and not (isinstance(href, str) and href.startswith("hpr/"))


def parse_otodom_items(
    raw_items: list[dict],
    city_config: CityConfig,
    transaction: str,
    market: str = MARKET_ALL,
) -> tuple[list[Listing], dict[str, int]]:
    listings: list[Listing] = []
    rejected: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    seen_slugs: set[str] = set()

    for raw in raw_items:
        # The title is used only to classify the listing in memory; it is removed right below.
        title_flags = classify_title(raw.get("title"))
        title_text = raw.get("title")
        # Strip PII immediately
        # relatedAds: unit ads nested in INVESTMENT tiles, each with its own owner and address
        for pii_key in ("advertOwner", "organisationAssignedMember", "agency",
                        "images", "title", "shortDescription", "relatedAds"):
            raw.pop(pii_key, None)
        addr = raw.get("location", {}).get("address", {})
        addr.pop("street", None)

        # Ad insert
        href = raw.get("href", "")
        if isinstance(href, str) and href.startswith("hpr/"):
            reject("ad_insert")
            continue

        # Dedup first: city-wide pages re-serve the same project tiles many times
        slug = raw.get("slug", "")
        if not slug:
            reject("no_slug")
            continue
        if slug in seen_slugs:
            reject("duplicate")
            continue
        seen_slugs.add(slug)

        # Developer project tiles: no single price or area; counted to show primary-market scale
        if raw.get("estate") == "INVESTMENT":
            reject("primary_market_project")
            continue
        if raw.get("estate") != "FLAT":
            reject("not_flat")
            continue

        # Shares and auctions are not comparable to ordinary flats: excluded from medians and results
        if FLAG_SHARE in title_flags:
            reject("share_listing")
            continue
        if FLAG_AUCTION in title_flags:
            reject("auction_listing")
            continue

        # Price
        total_price = raw.get("totalPrice") or {}
        price_val = total_price.get("value")
        currency = total_price.get("currency", city_config.currency)
        hide_price = raw.get("hidePrice", False)

        if hide_price or price_val is None or price_val <= 0:
            reject("hidden_or_zero_price")
            continue

        # Area
        area = raw.get("areaInSquareMeters")
        if not area or area <= 0:
            reject("no_area")
            continue

        # Location check
        locations = (
            raw.get("location", {})
            .get("reverseGeocoding", {})
            .get("locations", [])
        )
        city_name = None
        district = None
        in_city = False

        for loc in locations:
            level = loc.get("locationLevel")
            if level == "city_or_village":
                city_name = loc.get("name")
                loc_id = loc.get("id", "")
                if loc_id == city_config.location_path:
                    in_city = True
            elif level == "district":
                district = loc.get("name")

        city_slug = city_config.location_path.rsplit("/", 1)[-1]
        address_city = (raw.get("location", {}).get("address") or {}).get("city")
        misplaced = (
            names_other_city(city_slug, slug, title_text)
            or address_city_differs(city_slug, address_city)
        )
        if not in_city or misplaced:
            reject("outside_city")
            continue

        # Rent price (admin fee)
        rent_price_obj = raw.get("rentPrice") or {}
        admin_fee = rent_price_obj.get("value")

        # For rent listings: price_local = totalPrice (the actual rent)
        # admin_fee = rentPrice (the admin fee to the building)
        # Trap: swapped fields — admin_fee > rent → reject
        if transaction == "rent" and admin_fee is not None and admin_fee > price_val:
            reject("swapped_rent")
            continue

        # Rooms
        rooms_str = raw.get("roomsNumber")
        rooms = ROOMS_MAP.get(rooms_str)
        if rooms_str == "MORE":
            rooms = 10

        # Floor
        floor_str = raw.get("floorNumber")
        floor = FLOOR_MAP.get(floor_str) if floor_str else None

        # Primary market
        # market=SECONDARY is filtered by the portal, so False is certain. Under ALL only
        # developmentId > 0 is a (partial) signal for True; absence proves nothing -> None.
        dev_id = raw.get("developmentId")
        if market == MARKET_SECONDARY:
            is_primary: bool | None = False
        else:
            is_primary = True if dev_id is not None and dev_id > 0 else None

        # Advertiser type
        is_private = raw.get("isPrivateOwner")
        adv_type = "private" if is_private else "business" if is_private is False else None

        # Date
        first_pub = _parse_date(raw.get("createdAtFirst") or raw.get("dateCreated"))

        listing = Listing(
            source="otodom",
            listing_id=str(raw.get("id", "")),
            dedup_key=slug,
            url=f"{BASE_URL}/pl/oferta/{slug}",
            country=city_config.country,
            city=city_config.display_name,
            district=district,
            transaction=transaction,
            price_local=float(price_val),
            currency=currency,
            admin_fee_local=float(admin_fee) if admin_fee is not None else None,
            area_m2=float(area),
            rooms=rooms,
            floor=floor,
            is_primary_market=is_primary,
            advertiser_type=adv_type,
            first_published=first_pub,
            flags=(FLAG_NEEDS_RENOVATION,) if FLAG_NEEDS_RENOVATION in title_flags else (),
        )
        listings.append(listing)

    return listings, rejected


def _extract_next_data(html: str) -> dict:
    m = re.search(
        r'__NEXT_DATA__[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        raise ValueError("Could not find __NEXT_DATA__ in Otodom HTML")
    return json.loads(m.group(1))


def _extract_build_id(html: str) -> str:
    data = _extract_next_data(html)
    bid = data.get("buildId")
    if not bid:
        raise ValueError("No buildId in __NEXT_DATA__")
    return bid


def _parse_date(val: str | None) -> date | None:
    if not val:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(val[:19], fmt).date()
        except ValueError:
            continue
    return None

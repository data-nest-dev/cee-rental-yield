from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from src.config import CITIES, OTODOM_TRANSACTION_MAP, CityConfig
from src.http import HttpClient
from src.models import Listing

logger = logging.getLogger(__name__)

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

BASE_URL = "https://www.otodom.pl"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


class OtodomSource:
    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._build_id: str | None = None

    async def fetch_listings(
        self,
        city_key: str,
        transaction: str,
        max_listings: int,
    ) -> tuple[list[dict], dict]:
        cfg = CITIES[city_key]
        tx = OTODOM_TRANSACTION_MAP[transaction]
        stats = {
            "pages_fetched": 0,
            "raw_items": 0,
            "build_id_refreshes": 0,
            "fallback_to_html": False,
        }

        page1_items, pagination, build_id = await self._fetch_first_page(cfg, tx)
        self._build_id = build_id
        stats["pages_fetched"] = 1
        stats["raw_items"] = len(page1_items)

        all_items = list(page1_items)
        total_pages = pagination.get("totalPages", 1)
        items_needed = max_listings - len(all_items)

        for page_num in range(2, total_pages + 1):
            if items_needed <= 0:
                break
            page_items = await self._fetch_page(cfg, tx, page_num, stats)
            all_items.extend(page_items)
            stats["pages_fetched"] += 1
            stats["raw_items"] += len(page_items)
            items_needed -= len(page_items)

        return all_items, stats

    async def _fetch_first_page(
        self, cfg: CityConfig, tx: str,
    ) -> tuple[list[dict], dict, str]:
        url = f"{BASE_URL}/pl/wyniki/{tx}/mieszkanie/{cfg.location_path}"
        headers = {"User-Agent": USER_AGENT}
        status, body = await self._http.get(url, headers=headers)

        if status != 200:
            raise RuntimeError(f"Otodom first page returned {status}")

        build_id = _extract_build_id(body)
        next_data = _extract_next_data(body)
        page_props = next_data.get("props", {}).get("pageProps", next_data.get("pageProps", {}))
        items = page_props.get("data", {}).get("searchAds", {}).get("items", [])
        pagination = page_props.get("data", {}).get("searchAds", {}).get("pagination", {})

        return items, pagination, build_id

    async def _fetch_page(
        self, cfg: CityConfig, tx: str, page: int, stats: dict,
    ) -> list[dict]:
        if self._build_id and not stats.get("fallback_to_html"):
            items = await self._fetch_next_data_page(cfg, tx, page, stats)
            if items is not None:
                return items

        stats["fallback_to_html"] = True
        return await self._fetch_html_page(cfg, tx, page)

    async def _fetch_next_data_page(
        self, cfg: CityConfig, tx: str, page: int, stats: dict,
    ) -> list[dict] | None:
        segs = cfg.location_path.split("/")
        url = (
            f"{BASE_URL}/_next/data/{self._build_id}/pl/wyniki/{tx}"
            f"/mieszkanie/{cfg.location_path}.json"
        )
        params = {
            "page": str(page),
            "limit": "36",
            "ownerTypeSingleSelect": "ALL",
            "by": "DEFAULT",
            "direction": "DESC",
            "distanceRadius": "0",
            "searchingCriteria": [tx, "mieszkanie"] + segs,
        }
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "x-nextjs-data": "1",
            "Referer": f"{BASE_URL}/pl/wyniki/{tx}/mieszkanie/{cfg.location_path}",
        }

        # curl_cffi doesn't support repeated params via dict; build URL manually
        from urllib.parse import urlencode
        param_parts = [
            f"page={page}", "limit=36", "ownerTypeSingleSelect=ALL",
            "by=DEFAULT", "direction=DESC", "distanceRadius=0",
        ]
        for sc in [tx, "mieszkanie"] + segs:
            param_parts.append(f"searchingCriteria={sc}")
        full_url = url + "?" + "&".join(param_parts)

        status, body = await self._http.get(full_url, headers=headers)

        if status == 404:
            stats["build_id_refreshes"] += 1
            new_build_id = await self._refresh_build_id(cfg, tx)
            if new_build_id and new_build_id != self._build_id:
                full_url_new = full_url.replace(
                    f"/_next/data/{self._build_id}/",
                    f"/_next/data/{new_build_id}/",
                )
                self._build_id = new_build_id
                status, body = await self._http.get(full_url_new, headers=headers)
                if status == 404:
                    return None
            else:
                return None

        if status != 200:
            return None

        try:
            data = json.loads(body)
            return data.get("pageProps", {}).get("data", {}).get("searchAds", {}).get("items", [])
        except json.JSONDecodeError:
            return None

    async def _fetch_html_page(
        self, cfg: CityConfig, tx: str, page: int,
    ) -> list[dict]:
        url = f"{BASE_URL}/pl/wyniki/{tx}/mieszkanie/{cfg.location_path}?page={page}"
        headers = {"User-Agent": USER_AGENT}
        status, body = await self._http.get(url, headers=headers)
        if status != 200:
            logger.warning("Otodom HTML page %d returned %d", page, status)
            return []
        next_data = _extract_next_data(body)
        page_props = next_data.get("props", {}).get("pageProps", next_data.get("pageProps", {}))
        return page_props.get("data", {}).get("searchAds", {}).get("items", [])

    async def _refresh_build_id(self, cfg: CityConfig, tx: str) -> str | None:
        url = f"{BASE_URL}/pl/wyniki/{tx}/mieszkanie/{cfg.location_path}"
        headers = {"User-Agent": USER_AGENT}
        status, body = await self._http.get(url, headers=headers)
        if status != 200:
            return None
        try:
            return _extract_build_id(body)
        except ValueError:
            return None


def parse_otodom_items(
    raw_items: list[dict],
    city_config: CityConfig,
    transaction: str,
) -> tuple[list[Listing], dict[str, int]]:
    listings: list[Listing] = []
    rejected: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    seen_slugs: set[str] = set()

    for raw in raw_items:
        # Strip PII immediately
        for pii_key in ("advertOwner", "organisationAssignedMember", "agency",
                        "images", "title", "shortDescription"):
            raw.pop(pii_key, None)
        addr = raw.get("location", {}).get("address", {})
        addr.pop("street", None)

        # Ad insert
        href = raw.get("href", "")
        if isinstance(href, str) and href.startswith("hpr/"):
            reject("ad_insert")
            continue

        # Only flats
        if raw.get("estate") != "FLAT":
            reject("not_flat")
            continue

        # Dedup by slug
        slug = raw.get("slug", "")
        if not slug:
            reject("no_slug")
            continue
        if slug in seen_slugs:
            reject("duplicate")
            continue
        seen_slugs.add(slug)

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

        if not in_city:
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
        dev_id = raw.get("developmentId")
        is_primary = dev_id is not None and dev_id > 0

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

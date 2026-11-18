from __future__ import annotations

import json
import logging
import re

from src.config import CITIES, SREALITY_TRANSACTION_MAP, CityConfig
from src.http import HttpClient
from src.models import Listing

logger = logging.getLogger(__name__)

BASE_URL = "https://www.sreality.cz"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

# categorySubCb value → rooms count
CATEGORY_SUB_ROOMS: dict[int, int | None] = {
    2: 1,   # 1+kk
    3: 1,   # 1+1
    4: 2,   # 2+kk
    5: 2,   # 2+1
    6: 3,   # 3+kk
    7: 3,   # 3+1
    8: 4,   # 4+kk
    9: 4,   # 4+1
    10: 5,  # 5+kk
    11: 5,  # 5+1
    12: 6,  # 6+
    16: None,  # atypický
}


class SrealitySource:
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
        tx = SREALITY_TRANSACTION_MAP[transaction]
        stats = {
            "pages_fetched": 0,
            "raw_items": 0,
            "build_id_refreshes": 0,
            "fallback_to_html": False,
        }

        # Fetch first page (HTML to get buildId + data)
        page1_items, pagination, build_id = await self._fetch_first_page(cfg, tx)
        self._build_id = build_id
        stats["pages_fetched"] = 1
        stats["raw_items"] = len(page1_items)

        all_items = list(page1_items)
        total = pagination.get("total", 0)
        limit = pagination.get("limit", 22)
        total_pages = (total + limit - 1) // limit if limit > 0 else 1
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
        url = f"{BASE_URL}/hledani/{tx}/byty/{cfg.location_path}"
        headers = {"User-Agent": USER_AGENT}
        status, body = await self._http.get(url, headers=headers)

        if status != 200:
            raise RuntimeError(f"Sreality first page returned {status}")

        build_id = _extract_build_id(body)
        results, pagination = _extract_estates_from_html(body)
        return results, pagination, build_id

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
        url = (
            f"{BASE_URL}/_next/data/{self._build_id}/cs/hledani/{tx}"
            f"/byty/{cfg.location_path}.json?strana={page}"
        )
        headers = {
            "User-Agent": USER_AGENT,
            "x-nextjs-data": "1",
            "Accept": "*/*",
        }
        status, body = await self._http.get(url, headers=headers)

        if status == 404:
            stats["build_id_refreshes"] += 1
            new_id = await self._refresh_build_id(cfg, tx)
            if new_id and new_id != self._build_id:
                self._build_id = new_id
                url2 = url.replace(
                    f"/_next/data/{self._build_id}/",
                    f"/_next/data/{new_id}/",
                )
                status, body = await self._http.get(url2, headers=headers)
                if status == 404:
                    return None
            else:
                return None

        if status != 200:
            return None

        try:
            data = json.loads(body)
            pp = data.get("pageProps", {})
            return _find_estates_in_dehydrated(pp)
        except (json.JSONDecodeError, KeyError):
            return None

    async def _fetch_html_page(
        self, cfg: CityConfig, tx: str, page: int,
    ) -> list[dict]:
        url = f"{BASE_URL}/hledani/{tx}/byty/{cfg.location_path}?strana={page}"
        headers = {"User-Agent": USER_AGENT}
        status, body = await self._http.get(url, headers=headers)
        if status != 200:
            return []
        results, _ = _extract_estates_from_html(body)
        return results

    async def _refresh_build_id(self, cfg: CityConfig, tx: str) -> str | None:
        url = f"{BASE_URL}/hledani/{tx}/byty/{cfg.location_path}"
        headers = {"User-Agent": USER_AGENT}
        status, body = await self._http.get(url, headers=headers)
        if status != 200:
            return None
        try:
            return _extract_build_id(body)
        except ValueError:
            return None


def parse_sreality_items(
    raw_items: list[dict],
    city_config: CityConfig,
    transaction: str,
) -> tuple[list[Listing], dict[str, int]]:
    listings: list[Listing] = []
    rejected: dict[str, int] = {}
    seen_ids: set[int] = set()

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    for raw in raw_items:
        # Strip PII / content
        raw.pop("images", None)
        locality = raw.get("locality", {})
        locality.pop("street", None)
        locality.pop("streetId", None)
        locality.pop("streetSeoName", None)
        locality.pop("streetNumber", None)
        locality.pop("houseNumber", None)

        estate_id = raw.get("id")
        if not estate_id:
            reject("no_id")
            continue

        # Dedup
        if estate_id in seen_ids:
            reject("duplicate")
            continue
        seen_ids.add(estate_id)

        # Price
        price = raw.get("priceCzk")
        if price is None or price <= 1:
            reject("placeholder_price")
            continue

        # Area from name
        name = raw.get("name", "")
        area = _parse_area(name)
        if area is None or area <= 0:
            reject("no_area")
            continue

        # Rooms from categorySubCb
        cat_sub = raw.get("categorySubCb", {})
        cat_sub_val = cat_sub.get("value") if isinstance(cat_sub, dict) else None
        rooms = CATEGORY_SUB_ROOMS.get(cat_sub_val) if cat_sub_val else None

        # District from locality
        city_part = locality.get("cityPart")
        city_name = locality.get("city", city_config.display_name)

        # Build URL: /detail/{tx}/{category}/{sub_seo}/{city_seo}/{id}
        cat_type = raw.get("categoryTypeCb", {})
        tx_name = cat_type.get("name", "").lower() if isinstance(cat_type, dict) else ""
        cat_sub_name = cat_sub.get("name", "").lower().replace("+", "-") if isinstance(cat_sub, dict) else ""
        city_seo = locality.get("citySeoName", city_config.location_path)
        url = f"{BASE_URL}/detail/{tx_name}/byt/{cat_sub_name}/{city_seo}/{estate_id}"

        # Premise (agency) → advertiser type
        premise_id = raw.get("premiseId")
        adv_type = "business" if premise_id else "private"

        listing = Listing(
            source="sreality",
            listing_id=str(estate_id),
            dedup_key=str(estate_id),
            url=url,
            country=city_config.country,
            city=city_name,
            district=city_part,
            transaction=transaction,
            price_local=float(price),
            currency="CZK",
            admin_fee_local=None,
            area_m2=float(area),
            rooms=rooms,
            floor=None,
            is_primary_market=None,
            advertiser_type=adv_type,
            first_published=None,
        )
        listings.append(listing)

    return listings, rejected


def _parse_area(name: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m[²2]", name)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def _extract_build_id(html: str) -> str:
    m = re.search(
        r'__NEXT_DATA__[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        raise ValueError("No __NEXT_DATA__ in Sreality HTML")
    data = json.loads(m.group(1))
    bid = data.get("buildId")
    if not bid:
        raise ValueError("No buildId in Sreality __NEXT_DATA__")
    return bid


def _extract_estates_from_html(html: str) -> tuple[list[dict], dict]:
    m = re.search(
        r'__NEXT_DATA__[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        return [], {}
    data = json.loads(m.group(1))
    pp = data.get("props", {}).get("pageProps", {})
    results = _find_estates_in_dehydrated(pp)
    pagination = _find_pagination_in_dehydrated(pp)
    return results, pagination


def _find_estates_in_dehydrated(page_props: dict) -> list[dict]:
    ds = page_props.get("dehydratedState", {})
    for q in ds.get("queries", []):
        qk = q.get("queryKey", [])
        if isinstance(qk, list) and qk and qk[0] == "estatesSearch":
            return q.get("state", {}).get("data", {}).get("results", [])
    return []


def _find_pagination_in_dehydrated(page_props: dict) -> dict:
    ds = page_props.get("dehydratedState", {})
    for q in ds.get("queries", []):
        qk = q.get("queryKey", [])
        if isinstance(qk, list) and qk and qk[0] == "estatesSearch":
            return q.get("state", {}).get("data", {}).get("pagination", {})
    return {}

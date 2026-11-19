from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Listing:
    source: str
    listing_id: str
    dedup_key: str
    url: str
    country: str
    city: str
    district: str | None
    transaction: str
    price_local: float
    currency: str
    admin_fee_local: float | None
    area_m2: float
    rooms: int | None
    floor: int | None
    is_primary_market: bool | None
    advertiser_type: str | None
    first_published: date | None
    flags: tuple[str, ...] = ()  # atypical-listing flags derived from the title, which is never stored


@dataclass
class AreaYield:
    country: str
    city: str
    district: str | None
    rooms: str
    group_level: str
    confidence: str
    sale_count: int
    rent_count: int
    sale_price_per_m2_eur: dict
    rent_per_m2_monthly_eur: dict
    gross_yield_pct: float
    gross_yield_range_pct: list[float]
    local: dict
    fx: dict
    price_basis: str = "asking"
    sources: list[str] = field(default_factory=list)
    computed_at: str = ""


@dataclass
class ScoredListing:
    source: str
    listing_id: str
    url: str
    country: str
    city: str
    district: str | None
    rooms: int | None
    area_m2: float
    is_primary_market: bool | None
    price_local: float
    currency: str
    price_eur: float
    price_per_m2_eur: float
    group_median_price_per_m2_eur: float
    deal_score: int
    discount_vs_median_pct: float
    estimated_rent_monthly_eur: float
    gross_yield_pct: float
    group_level: str
    confidence: str
    days_on_market: int | None = None
    first_seen_at: str | None = None
    change_type: str | None = None
    price_cut_pct: float | None = None


@dataclass
class RunStats:
    cities: dict = field(default_factory=dict)
    fx_date: str | None = None
    fx_rates: dict = field(default_factory=dict)
    total_area_yields: int = 0
    total_scored_listings: int = 0
    errors: list[str] = field(default_factory=list)

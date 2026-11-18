from __future__ import annotations

from typing import Protocol

from src.models import Listing


class Source(Protocol):
    async def fetch_listings(
        self,
        city_key: str,
        transaction: str,
        max_listings: int,
    ) -> list[dict]:
        """Fetch raw listing dicts from the source."""
        ...


SOURCES: dict[str, Source] = {}


def register_source(name: str, source: Source) -> None:
    SOURCES[name] = source


def get_source(name: str) -> Source:
    return SOURCES[name]

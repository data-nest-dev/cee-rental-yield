from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0
BLOCK_RATE_LIMIT = 0.2
BLOCK_MIN_REQUESTS = 10


@dataclass
class DomainStats:
    requests: int = 0
    blocked: int = 0
    errors: int = 0
    bytes_downloaded: int = 0
    last_request_time: float = 0.0


@dataclass
class BlockWindow:
    label: str
    requests: int = 0
    blocked: int = 0


@dataclass
class HttpClient:
    proxy_url: str | None = None
    min_interval: float = 1.0
    domain_stats: dict[str, DomainStats] = field(default_factory=dict)
    _windows: dict[str, BlockWindow] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _session: AsyncSession | None = None

    def start_window(self, domain: str, label: str) -> None:
        """Start a fresh block-rate window for a domain (one per city x market side)."""
        self._windows[domain] = BlockWindow(label)

    def _get_domain(self, url: str) -> str:
        from urllib.parse import urlparse
        return urlparse(url).netloc

    def _get_lock(self, domain: str) -> asyncio.Lock:
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        return self._locks[domain]

    def _get_stats(self, domain: str) -> DomainStats:
        if domain not in self.domain_stats:
            self.domain_stats[domain] = DomainStats()
        return self.domain_stats[domain]

    async def _ensure_session(self) -> AsyncSession:
        if self._session is None:
            self._session = AsyncSession(impersonate="chrome")
        return self._session

    async def get(
        self,
        url: str,
        headers: dict | None = None,
        params: dict | None = None,
    ) -> tuple[int, str]:
        domain = self._get_domain(url)
        lock = self._get_lock(domain)
        stats = self._get_stats(domain)

        window = self._windows.setdefault(domain, BlockWindow("default"))
        if window.requests > BLOCK_MIN_REQUESTS and window.blocked / window.requests > BLOCK_RATE_LIMIT:
            raise BlockedError(
                f"{domain} blocked {window.blocked} of {window.requests} requests "
                f"({window.label}); try residential proxy PL"
            )

        async with lock:
            # Rate limit: 1 req/s per domain
            now = time.monotonic()
            elapsed = now - stats.last_request_time
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)

            session = await self._ensure_session()

            last_exc = None
            for attempt in range(MAX_RETRIES):
                try:
                    stats.last_request_time = time.monotonic()
                    stats.requests += 1
                    window.requests += 1

                    kwargs: dict = {
                        "headers": headers or {},
                        "params": params,
                        "timeout": 30,
                        "allow_redirects": True,
                    }
                    if self.proxy_url:
                        kwargs["proxy"] = self.proxy_url

                    resp = await session.get(url, **kwargs)
                    body = resp.text
                    stats.bytes_downloaded += len(body.encode())

                    if resp.status_code == 403 or _is_captcha(body):
                        stats.blocked += 1
                        window.blocked += 1
                        logger.warning(
                            "Blocked by %s (attempt %d/%d)",
                            domain, attempt + 1, MAX_RETRIES,
                        )
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(_backoff(attempt))
                            continue
                        return resp.status_code, body

                    if resp.status_code in (429, 500, 502, 503, 504):
                        stats.errors += 1
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(_backoff(attempt))
                            continue

                    return resp.status_code, body

                except Exception as e:
                    last_exc = e
                    stats.errors += 1
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(_backoff(attempt))
                        continue

            if last_exc:
                raise last_exc
            return 500, ""

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None


class BlockedError(Exception):
    pass


def _backoff(attempt: int) -> float:
    return BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)


def _is_captcha(body: str) -> bool:
    lower = body[:2000].lower()
    return "captcha" in lower or "are you a robot" in lower or "challenge-platform" in lower

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0
# Datacenter group BUYPROXIES94952 on the owner's account has 5 IPs; one session id per IP.
PROXY_SESSIONS = 5


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
    sessions: dict[str, dict[str, int]] = field(default_factory=dict)

    def count(self, session_id: str | None, blocked: bool) -> None:
        self.requests += 1
        self.blocked += blocked
        if session_id is not None:
            s = self.sessions.setdefault(session_id, {"requests": 0, "blocked": 0})
            s["requests"] += 1
            s["blocked"] += blocked


@dataclass
class HttpClient:
    proxy_url: str | None = None
    # Session-aware proxy (e.g. ProxyConfiguration.new_url); takes precedence over proxy_url.
    proxy_url_for: Callable[[str], Awaitable[str | None]] | None = None
    proxy_sessions: int = PROXY_SESSIONS
    min_interval: float = 1.0
    domain_stats: dict[str, DomainStats] = field(default_factory=dict)
    _windows: dict[str, BlockWindow] = field(default_factory=dict)
    _session_index: dict[str, int] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _session: AsyncSession | None = None

    def start_window(self, domain: str, label: str) -> None:
        """Start a fresh block-rate window for a domain (one per city x market side) on the next proxy session."""
        self._windows[domain] = BlockWindow(label)
        if self.proxy_url_for is not None:
            self._rotate_session(domain)

    def window(self, domain: str) -> BlockWindow | None:
        return self._windows.get(domain)

    def _rotate_session(self, domain: str) -> None:
        self._session_index[domain] = (self._session_index.get(domain, -1) + 1) % self.proxy_sessions

    def _session_id(self, domain: str) -> str | None:
        if self.proxy_url_for is None:
            return None
        return f"s{self._session_index.setdefault(domain, 0)}"

    async def _proxy_for(self, session_id: str | None) -> str | None:
        if self.proxy_url_for is not None and session_id is not None:
            return await self.proxy_url_for(session_id)
        return self.proxy_url

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
        follow_redirect_prefix: str | tuple[str, ...] | None = None,
    ) -> tuple[int, str]:
        """GET through the per-domain limiter. HTTP redirects are never followed by the client itself.

        With `follow_redirect_prefix` (a path prefix such as "/pl/wyniki/", or a tuple of them) one redirect hop
        is followed by hand: it goes through the limiter like any request, is counted in the request counters,
        and must stay on the same domain under that prefix; anything else raises RedirectError. Without it a
        redirect status is returned as is.
        """
        status, body, location = await self._request(url, headers, params)
        if status not in REDIRECT_STATUSES or follow_redirect_prefix is None:
            return status, body
        target = _redirect_target(url, location, follow_redirect_prefix)
        status, body, location = await self._request(target, headers, params)
        if status in REDIRECT_STATUSES:
            raise RedirectError("Server redirected more than once; refusing to follow further.")
        return status, body

    async def _request(
        self,
        url: str,
        headers: dict | None = None,
        params: dict | None = None,
    ) -> tuple[int, str, str | None]:
        """One request through the limiter. Retries only network errors and 5xx; 403, 429 and captcha end the run."""
        domain = self._get_domain(url)
        lock = self._get_lock(domain)
        stats = self._get_stats(domain)
        window = self._windows.setdefault(domain, BlockWindow("default"))

        async with lock:
            # Rate limit: 1 req/s per domain
            now = time.monotonic()
            elapsed = now - stats.last_request_time
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)

            session = await self._ensure_session()

            last_exc = None
            for attempt in range(MAX_RETRIES):
                session_id = self._session_id(domain)
                proxy: str | None = None
                try:
                    stats.last_request_time = time.monotonic()
                    stats.requests += 1

                    kwargs: dict = {
                        "headers": headers or {},
                        "params": params,
                        "timeout": 30,
                        "allow_redirects": False,
                    }
                    proxy = await self._proxy_for(session_id)
                    if proxy:
                        kwargs["proxy"] = proxy

                    resp = await session.get(url, **kwargs)
                    if proxy and _is_proxy_refusal(resp.status_code, None):
                        raise ProxyAccessError(PROXY_ACCESS_MESSAGE)
                    body = resp.text
                    stats.bytes_downloaded += len(body.encode())

                    captcha = _is_captcha(body)
                    if resp.status_code in (403, 429) or captcha:
                        stats.blocked += 1
                        window.count(session_id, blocked=True)
                        logger.warning("Blocked by %s (HTTP %d, session %s); stopping the run",
                                       domain, resp.status_code, session_id)
                        raise PortalBlockedError(
                            f"{domain} refused the request (HTTP {resp.status_code}"
                            f"{', captcha' if captcha else ''}; {window.label}). "
                            "The Actor does not retry or work around blocks, so the run stopped. "
                            "Try again later or use a different proxy configuration."
                        )

                    window.count(session_id, blocked=False)

                    if resp.status_code in (500, 502, 503, 504):
                        stats.errors += 1
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(_backoff(attempt))
                            continue

                    return resp.status_code, body, resp.headers.get("location")

                except BlockedError:
                    raise
                except Exception as e:
                    if proxy and _is_proxy_refusal(None, e):
                        raise ProxyAccessError(PROXY_ACCESS_MESSAGE) from e
                    last_exc = e
                    stats.errors += 1
                    window.count(session_id, blocked=False)
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(_backoff(attempt))
                        continue

            if last_exc:
                raise last_exc
            return 500, "", None

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None


class BlockedError(Exception):
    pass


class PortalBlockedError(BlockedError):
    """The portal answered 403, 429 or a captcha. Ends the run: no retry, no new session, no workaround."""


REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class RedirectError(Exception):
    """A redirect the client refuses to follow (other domain, other path, or more than one hop)."""


def _redirect_target(url: str, location: str | None, prefix: str | tuple[str, ...]) -> str:
    from urllib.parse import urljoin, urlsplit
    if not location:
        raise RedirectError("Server redirected without a Location header.")
    target = urljoin(url, location)
    old, new = urlsplit(url), urlsplit(target)
    if new.scheme != old.scheme or new.netloc != old.netloc or not new.path.startswith(prefix) or ".." in new.path:
        raise RedirectError(f"Server redirected outside {old.netloc}; refusing to follow.")
    return target


class ProxyAccessError(BlockedError):
    """The proxy itself refused us (bad credentials or a group the account cannot use); not a portal block."""


PROXY_ACCESS_MESSAGE = (
    "Apify Proxy refused the connection (HTTP 407/597), most likely because your account has no access to the "
    "selected proxy group. Use the default automatic proxy, choose a group listed on the Proxy page of your "
    "Apify Console, or pass your own proxyConfiguration."
)


def _is_proxy_refusal(status: int | None, exc: Exception | None) -> bool:
    if status in (407, 597):
        return True
    text = str(exc or "")
    return "CONNECT tunnel failed" in text or "Proxy Authentication" in text or "response 407" in text


def _backoff(attempt: int) -> float:
    return BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)


def _is_captcha(body: str) -> bool:
    lower = body[:2000].lower()
    return "captcha" in lower or "are you a robot" in lower or "challenge-platform" in lower

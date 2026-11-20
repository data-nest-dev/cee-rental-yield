from __future__ import annotations

from dataclasses import dataclass

import pytest

import src.http as http_mod
from src.http import BlockedError, HttpClient

DOMAIN = "www.otodom.pl"
URL = f"https://{DOMAIN}/x"


@dataclass
class _Resp:
    status_code: int
    text: str = "{}"


class FakeSession:
    def __init__(self, statuses: list[int]) -> None:
        self.statuses = statuses

    async def get(self, url: str, **kwargs) -> _Resp:
        return _Resp(self.statuses.pop(0) if self.statuses else 200)

    async def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_mod, "_backoff", lambda attempt: 0)


def _client(statuses: list[int]) -> HttpClient:
    client = HttpClient(min_interval=0)
    client._session = FakeSession(statuses)
    return client


@pytest.mark.asyncio
async def test_aborts_when_window_block_rate_exceeds_20_percent() -> None:
    # 8 OK, then one URL blocked on all 3 attempts -> 3 of 11 requests blocked (27%)
    client = _client([200] * 8 + [403, 403, 403])
    client.start_window(DOMAIN, "katowice sale")
    for _ in range(9):
        await client.get(URL)
    with pytest.raises(BlockedError, match=r"blocked 3 of 11 requests \(katowice sale\)"):
        await client.get(URL)


@pytest.mark.asyncio
async def test_new_window_resets_block_rate() -> None:
    client = _client([200] * 8 + [403, 403, 403])
    client.start_window(DOMAIN, "katowice sale")
    for _ in range(9):
        await client.get(URL)
    client.start_window(DOMAIN, "katowice rent")
    status, _ = await client.get(URL)
    assert status == 200
    # domain totals still accumulate for reporting
    assert client.domain_stats[DOMAIN].blocked == 3
    assert client.domain_stats[DOMAIN].requests == 12


@pytest.mark.asyncio
async def test_below_minimum_requests_does_not_abort() -> None:
    client = _client([403] * 9 + [200])
    client.start_window(DOMAIN, "w")
    for _ in range(3):
        await client.get(URL)  # 9 blocked attempts of 9 requests
    status, _ = await client.get(URL)
    assert status == 200


class RecordingSession(FakeSession):
    def __init__(self, statuses: list[int]) -> None:
        super().__init__(statuses)
        self.proxies: list[str | None] = []

    async def get(self, url: str, **kwargs) -> _Resp:
        self.proxies.append(kwargs.get("proxy"))
        return await super().get(url, **kwargs)


def _proxied_client(statuses: list[int], sessions: int = 5) -> tuple[HttpClient, RecordingSession]:
    async def proxy_url_for(session_id: str) -> str:
        return f"http://{session_id}.proxy"
    client = HttpClient(min_interval=0, proxy_url_for=proxy_url_for, proxy_sessions=sessions)
    fake = RecordingSession(statuses)
    client._session = fake
    return client, fake


@pytest.mark.asyncio
async def test_each_window_starts_on_the_next_session_round_robin() -> None:
    client, fake = _proxied_client([200] * 6, sessions=3)
    for label in ("katowice sale", "katowice rent", "warszawa sale", "warszawa rent"):
        client.start_window(DOMAIN, label)
        await client.get(URL)
    assert fake.proxies == ["http://s0.proxy", "http://s1.proxy", "http://s2.proxy", "http://s0.proxy"]


@pytest.mark.asyncio
async def test_block_rotates_to_next_session_before_retry_and_counts_per_session() -> None:
    client, fake = _proxied_client([403, 200])
    client.start_window(DOMAIN, "katowice sale")
    status, _ = await client.get(URL)
    assert status == 200
    assert fake.proxies == ["http://s0.proxy", "http://s1.proxy"]
    w = client.window(DOMAIN)
    assert (w.requests, w.blocked) == (2, 1)
    assert w.sessions == {"s0": {"requests": 1, "blocked": 1}, "s1": {"requests": 1, "blocked": 0}}


@pytest.mark.asyncio
async def test_static_proxy_url_still_used_without_provider() -> None:
    client = HttpClient(min_interval=0, proxy_url="http://static.proxy")
    fake = RecordingSession([200])
    client._session = fake
    client.start_window(DOMAIN, "w")
    await client.get(URL)
    assert fake.proxies == ["http://static.proxy"]
    assert client.window(DOMAIN).sessions == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [407, 597])
async def test_proxy_refusal_status_raises_proxy_access_error_without_retrying(status: int) -> None:
    client, fake = _proxied_client([status, 200])
    client.start_window(DOMAIN, "w")
    with pytest.raises(http_mod.ProxyAccessError, match="no access to the selected proxy group"):
        await client.get(URL)
    assert len(fake.proxies) == 1


@pytest.mark.asyncio
async def test_connect_tunnel_failure_with_proxy_raises_proxy_access_error() -> None:
    client, fake = _proxied_client([])

    async def boom(url: str, **kwargs):
        raise RuntimeError("CONNECT tunnel failed, response 407")
    fake.get = boom  # type: ignore[method-assign]
    with pytest.raises(http_mod.ProxyAccessError):
        await client.get(URL)

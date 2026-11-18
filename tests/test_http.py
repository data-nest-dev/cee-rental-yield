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

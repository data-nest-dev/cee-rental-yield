from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import src.http as http_mod
from src.http import HttpClient, PortalBlockedError, RedirectError

DOMAIN = "www.otodom.pl"
URL = f"https://{DOMAIN}/x"


@dataclass
class _Resp:
    status_code: int
    text: str = "{}"
    headers: dict = field(default_factory=dict)


class FakeSession:
    def __init__(self, statuses: list) -> None:
        self.statuses = statuses
        self.urls: list[str] = []

    async def get(self, url: str, **kwargs) -> _Resp:
        self.urls.append(url)
        item = self.statuses.pop(0) if self.statuses else 200
        return item if isinstance(item, _Resp) else _Resp(item)

    async def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_mod, "_backoff", lambda attempt: 0)


def _client(statuses: list) -> HttpClient:
    client = HttpClient(min_interval=0)
    client._session = FakeSession(statuses)
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429])
async def test_block_status_ends_the_run_without_retry(status: int) -> None:
    client = _client([status, 200])
    client.start_window(DOMAIN, "katowice sale")
    with pytest.raises(PortalBlockedError, match=rf"HTTP {status}; katowice sale"):
        await client.get(URL)
    assert len(client._session.urls) == 1
    assert client.domain_stats[DOMAIN].blocked == 1 and client.domain_stats[DOMAIN].requests == 1


@pytest.mark.asyncio
async def test_captcha_page_ends_the_run_without_retry() -> None:
    client = _client([_Resp(200, "<html>Please solve the CAPTCHA</html>"), 200])
    with pytest.raises(PortalBlockedError, match="captcha"):
        await client.get(URL)
    assert len(client._session.urls) == 1


@pytest.mark.asyncio
async def test_block_does_not_rotate_the_proxy_session() -> None:
    client, fake = _proxied_client([403, 200])
    client.start_window(DOMAIN, "w")
    with pytest.raises(PortalBlockedError):
        await client.get(URL)
    assert fake.proxies == ["http://s0.proxy"]
    assert client._session_id(DOMAIN) == "s0"


@pytest.mark.asyncio
async def test_server_errors_are_retried_up_to_three_attempts() -> None:
    client = _client([503, 502, 200])
    status, _ = await client.get(URL)
    assert status == 200 and len(client._session.urls) == 3
    client = _client([500, 500, 500, 200])
    status, _ = await client.get(URL)
    assert status == 500 and len(client._session.urls) == 3


@pytest.mark.asyncio
async def test_network_errors_are_retried() -> None:
    client = _client([])
    calls = {"n": 0}

    async def flaky(url: str, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("reset")
        return _Resp(200)
    client._session.get = flaky  # type: ignore[method-assign]
    status, _ = await client.get(URL)
    assert status == 200 and calls["n"] == 3


@pytest.mark.asyncio
async def test_client_never_lets_the_session_follow_redirects() -> None:
    seen: dict = {}
    client = _client([])

    async def spy(url: str, **kwargs):
        seen.update(kwargs)
        return _Resp(200)
    client._session.get = spy  # type: ignore[method-assign]
    await client.get(URL)
    assert seen["allow_redirects"] is False


@pytest.mark.asyncio
async def test_redirect_is_returned_as_is_without_a_follow_prefix() -> None:
    client = _client([_Resp(301, "", {"location": "/pl/wyniki/y"})])
    status, _ = await client.get(URL)
    assert status == 301 and len(client._session.urls) == 1


@pytest.mark.asyncio
async def test_redirect_hop_goes_through_the_limiter_and_is_counted() -> None:
    client = _client([_Resp(301, "", {"location": "/pl/wyniki/y"}), _Resp(200, "ok")])
    status, body = await client.get(URL, follow_redirect_prefix="/pl/wyniki/")
    assert (status, body) == (200, "ok")
    assert client._session.urls == [URL, f"https://{DOMAIN}/pl/wyniki/y"]
    assert client.domain_stats[DOMAIN].requests == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("location", [
    "https://evil.example/pl/wyniki/y",
    "/pl/oferta/z",
    "/pl/wyniki/../oferta/z",
    None,
])
async def test_redirect_outside_the_prefix_or_domain_is_refused(location: str | None) -> None:
    headers = {"location": location} if location else {}
    client = _client([_Resp(302, "", headers), 200])
    with pytest.raises(RedirectError):
        await client.get(URL, follow_redirect_prefix="/pl/wyniki/")
    assert len(client._session.urls) == 1


@pytest.mark.asyncio
async def test_second_redirect_is_refused() -> None:
    client = _client([_Resp(301, "", {"location": "/pl/wyniki/y"}), _Resp(301, "", {"location": "/pl/wyniki/z"})])
    with pytest.raises(RedirectError, match="more than once"):
        await client.get(URL, follow_redirect_prefix="/pl/wyniki/")
    assert len(client._session.urls) == 2


@pytest.mark.asyncio
async def test_new_window_keeps_domain_totals() -> None:
    client = _client([200] * 3)
    client.start_window(DOMAIN, "katowice sale")
    await client.get(URL)
    await client.get(URL)
    client.start_window(DOMAIN, "katowice rent")
    await client.get(URL)
    assert client.window(DOMAIN).requests == 1
    assert client.domain_stats[DOMAIN].requests == 3


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

from __future__ import annotations

import logging

from apify import Actor

from src.http import HttpClient
from src.inputs import RunInput
from src.pipeline import run

logger = logging.getLogger(__name__)


class ApifyActorPort:
    """Adapts apify.Actor to the pipeline's ActorPort."""

    async def push(self, records: list[dict], event: str | None) -> tuple[int, bool]:
        if records:
            await Actor.push_data(records)
        return len(records), False

    async def set_value(self, key: str, value: dict) -> None:
        await Actor.set_value(key, value)

    async def fail(self, message: str) -> None:
        await Actor.fail(status_message=message)

    async def status(self, message: str) -> None:
        await Actor.set_status_message(message)


async def make_http(run_input: RunInput) -> HttpClient:
    # Proxy access from outside Actors is disabled on the owner's account, so local runs go direct.
    if not Actor.is_at_home() or not run_input.proxy_configuration:
        return HttpClient()
    proxy = await Actor.create_proxy_configuration(actor_proxy_input=run_input.proxy_configuration)
    if proxy is None:
        return HttpClient()

    async def proxy_url_for(session_id: str) -> str | None:
        return await proxy.new_url(session_id=session_id)

    return HttpClient(proxy_url_for=proxy_url_for)


async def main() -> None:
    async with Actor:
        raw_input = await Actor.get_input() or {}
        await run(ApifyActorPort(), raw_input, http_factory=make_http)

"""Runs the real Actor adapter + pipeline under `async with Actor:` with a fake source (no network)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from apify import Actor  # noqa: E402

from src.http import HttpClient  # noqa: E402
from src.main import ApifyActorPort  # noqa: E402
from src.pipeline import run  # noqa: E402
from test_pipeline import FakeSource, _rates  # noqa: E402


async def main(scenario: dict) -> None:
    source = FakeSource(replicate=scenario.get("replicate", 1))

    async def http_factory(run_input):
        return HttpClient()

    async with Actor:
        await run(ApifyActorPort(), scenario["input"], http_factory=http_factory,
                  source_factory=lambda http: source, rates_loader=_rates)


if __name__ == "__main__":
    asyncio.run(main(json.loads(sys.argv[1])))

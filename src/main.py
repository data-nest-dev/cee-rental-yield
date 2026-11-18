from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def main() -> None:
    try:
        from apify import Actor
    except ImportError:
        logger.info("Running outside Apify platform")
        return

    async with Actor:
        actor_input = await Actor.get_input() or {}
        cities = actor_input.get("cities", ["warszawa", "krakow"])
        mode = actor_input.get("mode", "both")
        logger.info("Starting cee-rental-yield for cities=%s mode=%s", cities, mode)
        # Full orchestration will be implemented in M2/M3
        logger.info("M1 skeleton — orchestration not yet implemented")

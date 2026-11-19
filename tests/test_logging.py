from __future__ import annotations

import io
import logging

from src.main import configure_app_logging


def test_info_lines_of_our_modules_are_emitted_under_actor_logging() -> None:
    src_logger = logging.getLogger("src")
    saved = (src_logger.handlers[:], src_logger.level, src_logger.propagate)
    try:
        logging.getLogger().setLevel(logging.WARNING)  # what the platform root logger looks like
        configure_app_logging()
        stream = io.StringIO()
        src_logger.handlers[0].stream = stream
        logging.getLogger("src.sources.otodom").info("Fetching warszawa sale")
        assert logging.getLogger("src.sources.otodom").isEnabledFor(logging.INFO)
        assert "Fetching warszawa sale" in stream.getvalue()
    finally:
        src_logger.handlers[:], src_logger.level, src_logger.propagate = saved[0], saved[1], saved[2]

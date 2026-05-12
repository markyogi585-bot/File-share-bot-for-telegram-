"""
Logger — structured logging for Railway + local dev.
"""

import logging
import os
import sys


def setup_logger(name: str) -> logging.Logger:
    level = logging.DEBUG if os.getenv("DEBUG", "").lower() == "true" else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            # File handler for /logs command
            logging.FileHandler("bot.log", encoding="utf-8"),
        ],
    )

    # Suppress noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    return logging.getLogger(name)

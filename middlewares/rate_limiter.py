"""
Rate Limiter — per-user upload/download limits using in-memory + MongoDB.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Dict, Tuple

from config import Config

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Sliding window rate limiter.
    Tracks: (user_id, action) -> list of timestamps
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        # {(user_id, action): [timestamp, ...]}
        self._windows: Dict[Tuple[int, str], list] = defaultdict(list)

    def check(self, user_id: int, action: str) -> bool:
        """
        Returns True if action is allowed.
        Actions: 'upload', 'download', 'command'
        """
        now = time.time()
        window = 60  # 1 minute sliding window

        limits = {
            "upload": self.cfg.RATE_LIMIT_UPLOADS_PER_MIN,
            "download": self.cfg.RATE_LIMIT_DOWNLOADS_PER_MIN,
            "command": 30,
        }
        limit = limits.get(action, 20)

        key = (user_id, action)
        # Remove old timestamps
        self._windows[key] = [t for t in self._windows[key] if now - t < window]

        if len(self._windows[key]) >= limit:
            return False

        self._windows[key].append(now)
        return True

    def get_wait_time(self, user_id: int, action: str) -> int:
        """How many seconds until next allowed action."""
        now = time.time()
        key = (user_id, action)
        if not self._windows[key]:
            return 0
        oldest = min(self._windows[key])
        return max(0, int(60 - (now - oldest)))

    def reset(self, user_id: int) -> None:
        """Reset all limits for a user (admin action)."""
        keys_to_del = [k for k in self._windows if k[0] == user_id]
        for k in keys_to_del:
            del self._windows[k]

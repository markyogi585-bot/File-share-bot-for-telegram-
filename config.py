"""
Configuration — all settings from environment variables.
Railway me bas .env ya Variables tab me set karo.
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    # ─── Core Bot ────────────────────────────────────────────
    BOT_TOKEN: str = field(default_factory=lambda: os.environ["BOT_TOKEN"])
    BOT_USERNAME: str = field(default_factory=lambda: os.getenv("BOT_USERNAME", ""))

    # ─── Admin ───────────────────────────────────────────────
    # Comma-separated admin IDs, e.g. "123456789,987654321"
    ADMIN_IDS: List[int] = field(default_factory=lambda: [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ])

    # ─── Database ────────────────────────────────────────────
    MONGO_URI: str = field(default_factory=lambda: os.environ["MONGO_URI"])
    DB_NAME: str = field(default_factory=lambda: os.getenv("DB_NAME", "tg_filebot"))

    # ─── Force Join Channels ─────────────────────────────────
    # Comma-separated, e.g. "@mychannel1,@mychannel2"
    FORCE_JOIN_CHANNELS: List[str] = field(default_factory=lambda: [
        x.strip() for x in os.getenv("FORCE_JOIN_CHANNELS", "").split(",") if x.strip()
    ])
    FORCE_JOIN_ENABLED: bool = field(default_factory=lambda: os.getenv("FORCE_JOIN_ENABLED", "true").lower() == "true")

    # ─── File Storage Channel ────────────────────────────────
    # Private channel ID where files are stored (e.g. -100123456789)
    STORAGE_CHANNEL_ID: int = field(default_factory=lambda: int(os.getenv("STORAGE_CHANNEL_ID", "0")))

    # ─── Encryption ──────────────────────────────────────────
    # 32-byte hex key for AES-256 encryption
    ENCRYPTION_KEY: str = field(default_factory=lambda: os.getenv("ENCRYPTION_KEY", ""))

    # ─── File Limits ─────────────────────────────────────────
    MAX_FILE_SIZE_MB: int = field(default_factory=lambda: int(os.getenv("MAX_FILE_SIZE_MB", "2000")))
    MAX_FILES_PER_USER: int = field(default_factory=lambda: int(os.getenv("MAX_FILES_PER_USER", "1000")))
    FREE_STORAGE_MB: int = field(default_factory=lambda: int(os.getenv("FREE_STORAGE_MB", "5000")))

    # ─── Rate Limiting ───────────────────────────────────────
    RATE_LIMIT_UPLOADS_PER_MIN: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_UPLOADS_PER_MIN", "10")))
    RATE_LIMIT_DOWNLOADS_PER_MIN: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_DOWNLOADS_PER_MIN", "20")))

    # ─── Webhook (Railway Production) ────────────────────────
    WEBHOOK_URL: str = field(default_factory=lambda: os.getenv("WEBHOOK_URL", ""))

    # ─── Bot Messages / Branding ─────────────────────────────
    BOT_NAME: str = field(default_factory=lambda: os.getenv("BOT_NAME", "FileVault Bot"))
    SUPPORT_USERNAME: str = field(default_factory=lambda: os.getenv("SUPPORT_USERNAME", ""))

    # ─── Maintenance Mode ────────────────────────────────────
    MAINTENANCE_MODE: bool = field(default_factory=lambda: os.getenv("MAINTENANCE_MODE", "false").lower() == "true")

    # ─── Auto Delete ─────────────────────────────────────────
    AUTO_DELETE_SECONDS: int = field(default_factory=lambda: int(os.getenv("AUTO_DELETE_SECONDS", "0")))  # 0 = disabled

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.ADMIN_IDS

    def validate(self):
        assert self.BOT_TOKEN, "BOT_TOKEN is required"
        assert self.MONGO_URI, "MONGO_URI is required"
        assert self.STORAGE_CHANNEL_ID != 0, "STORAGE_CHANNEL_ID is required"
        return self

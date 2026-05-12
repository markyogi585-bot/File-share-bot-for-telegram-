"""
Bot Scheduler — Auto cleanup, stats recording, expired file deletion.
Uses APScheduler running inside the bot process.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

from database.mongodb import Database

logger = logging.getLogger(__name__)


class BotScheduler:

    def __init__(self, app: Application):
        self.app = app
        self.scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

    async def start(self) -> None:
        # Auto cleanup expired files — every hour
        self.scheduler.add_job(
            self._cleanup_expired_files,
            "interval",
            hours=1,
            id="cleanup_expired",
            replace_existing=True,
        )

        # Daily stats log — every midnight
        self.scheduler.add_job(
            self._log_daily_stats,
            "cron",
            hour=0,
            minute=0,
            id="daily_stats",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info("✅ Scheduler started")

    async def _cleanup_expired_files(self) -> None:
        """Mark expired files as deleted."""
        expired = await Database.get_expired_files()
        if not expired:
            return

        logger.info(f"🗑️ Cleaning up {len(expired)} expired files")
        for f in expired:
            await Database.delete_file(f["file_key"], f["owner_id"])

    async def _log_daily_stats(self) -> None:
        """Log daily statistics."""
        stats = await Database.get_stats()
        logger.info(
            f"📊 Daily Stats — Users: {stats['total_users']}, "
            f"Files: {stats['total_files']}, "
            f"Storage: {stats['total_storage_bytes']} bytes"
        )

    async def stop(self) -> None:
        self.scheduler.shutdown()

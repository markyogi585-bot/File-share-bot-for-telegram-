"""
Force Join Middleware — user ko channel join karwata hai before any action.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.error import TelegramError

from config import Config
from database.mongodb import Database

logger = logging.getLogger(__name__)


class ForceJoinMiddleware:

    def __init__(self, cfg: Config):
        self.cfg = cfg

    async def check_membership(self, bot: Bot, user_id: int) -> tuple[bool, List[dict]]:
        """
        Returns (all_joined, not_joined_channels)
        """
        if not self.cfg.FORCE_JOIN_ENABLED:
            return True, []

        db_channels = await Database.get_force_channels()
        channels = db_channels if db_channels else [
            {"channel_id": ch, "channel_name": ch} for ch in self.cfg.FORCE_JOIN_CHANNELS
        ]

        if not channels:
            return True, []

        not_joined = []
        for ch in channels:
            channel_id = ch["channel_id"]
            try:
                member: ChatMember = await bot.get_chat_member(channel_id, user_id)
                if member.status in ("left", "kicked", "banned"):
                    not_joined.append(ch)
            except TelegramError as e:
                logger.warning(f"Force join check failed for {channel_id}: {e}")
                # If we can't check, skip that channel (don't block user)

        return len(not_joined) == 0, not_joined

    async def send_join_request(self, bot: Bot, chat_id: int, not_joined: List[dict]) -> None:
        """Send join request message with buttons."""
        buttons = []
        for ch in not_joined:
            channel_id = ch["channel_id"]
            channel_name = ch.get("channel_name", channel_id)
            # Build invite link
            if str(channel_id).startswith("@"):
                link = f"https://t.me/{channel_id.lstrip('@')}"
            else:
                try:
                    invite = await bot.export_chat_invite_link(channel_id)
                    link = invite
                except Exception:
                    link = f"https://t.me/{channel_id}"
            buttons.append([InlineKeyboardButton(f"📢 Join {channel_name}", url=link)])

        buttons.append([InlineKeyboardButton("✅ Maine Join Kar Liya", callback_data="verify_join")])

        markup = InlineKeyboardMarkup(buttons)
        text = (
            "🔐 <b>Access Restricted!</b>\n\n"
            "Bot use karne ke liye pehle yeh channels join karo:\n\n"
            + "\n".join(f"• {ch.get('channel_name', ch['channel_id'])}" for ch in not_joined)
            + "\n\n<i>Join karne ke baad ✅ button dabao.</i>"
        )
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="HTML")

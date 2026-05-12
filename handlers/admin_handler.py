"""
Admin Handler — Full Admin Panel
/admin, /broadcast, /ban, /unban, /addchannel, /setlimit, /logs, /botinfo etc.
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from typing import List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from config import Config
from database.mongodb import Database
from utils.helpers import format_size, escape_html

logger = logging.getLogger(__name__)


def admin_only(func):
    """Decorator: block non-admins."""
    async def wrapper(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or not self.cfg.is_admin(user.id):
            await update.effective_message.reply_text("🚫 Admin only command!")
            return
        return await func(self, update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


class AdminHandler:

    def __init__(self, cfg: Config):
        self.cfg = cfg

    # ─── Admin Panel ─────────────────────────────────────────

    @admin_only
    async def handle_admin_panel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        stats = await Database.get_stats()

        buttons = [
            [
                InlineKeyboardButton("📊 Full Stats", callback_data="admin_stats"),
                InlineKeyboardButton("👥 Users", callback_data="admin_users"),
            ],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
                InlineKeyboardButton("📋 Channels", callback_data="admin_channels"),
            ],
            [
                InlineKeyboardButton("🔧 Force Join", callback_data="admin_forcejoin"),
                InlineKeyboardButton("🚨 Maintenance", callback_data="admin_maintenance"),
            ],
            [
                InlineKeyboardButton("📁 All Files", callback_data="admin_files"),
                InlineKeyboardButton("📜 Logs", callback_data="admin_logs"),
            ],
            [InlineKeyboardButton("ℹ️ Bot Info", callback_data="admin_botinfo")],
        ]

        text = (
            "🔑 <b>Admin Panel</b>\n\n"
            f"👥 Users: <b>{stats['total_users']:,}</b>\n"
            f"🟢 Active Today: <b>{stats['active_today']:,}</b>\n"
            f"📁 Files: <b>{stats['total_files']:,}</b>\n"
            f"💾 Storage: <b>{format_size(stats['total_storage_bytes'])}</b>\n\n"
            f"📤 Today Uploads: {stats['today_uploads']:,}\n"
            f"📥 Today Downloads: {stats['today_downloads']:,}\n\n"
            f"🔧 Maintenance: {'ON 🔴' if self.cfg.MAINTENANCE_MODE else 'OFF 🟢'}\n"
            f"🔐 Force Join: {'ON 🟢' if self.cfg.FORCE_JOIN_ENABLED else 'OFF 🔴'}"
        )

        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

    # ─── Broadcast ────────────────────────────────────────────

    @admin_only
    async def handle_broadcast(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if not args:
            await update.message.reply_text(
                "Usage: <code>/broadcast Your message here</code>\n\n"
                "Supports HTML formatting. Sabhi active users ko message jayega.",
                parse_mode=ParseMode.HTML
            )
            return

        message_text = " ".join(args)
        users = await Database.get_all_users(banned=False)
        total = len(users)

        progress_msg = await update.message.reply_text(f"📢 Broadcasting to {total} users...")

        success, failed = 0, 0
        for i, user in enumerate(users):
            try:
                await ctx.bot.send_message(
                    chat_id=user["user_id"],
                    text=f"📢 <b>Announcement</b>\n\n{message_text}",
                    parse_mode=ParseMode.HTML
                )
                success += 1
            except TelegramError:
                failed += 1

            # Update progress every 50 users
            if (i + 1) % 50 == 0:
                try:
                    await progress_msg.edit_text(
                        f"📢 Broadcasting... {i+1}/{total}\n✅ {success} | ❌ {failed}"
                    )
                except Exception:
                    pass

            # Small delay to avoid flood
            import asyncio
            await asyncio.sleep(0.05)

        await progress_msg.edit_text(
            f"✅ <b>Broadcast Complete!</b>\n\n"
            f"📤 Sent: {success}\n"
            f"❌ Failed: {failed}\n"
            f"👥 Total: {total}",
            parse_mode=ParseMode.HTML
        )

    # ─── Ban / Unban ──────────────────────────────────────────

    @admin_only
    async def handle_ban(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: <code>/ban user_id [reason]</code>", parse_mode=ParseMode.HTML)
            return

        target_id = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else "No reason given"

        if self.cfg.is_admin(target_id):
            await update.message.reply_text("❌ Admin ko ban nahi kar sakte!")
            return

        success = await Database.ban_user(target_id)
        if success:
            await update.message.reply_text(
                f"🚫 <b>User Banned!</b>\n\n🆔 {target_id}\n📝 {escape_html(reason)}",
                parse_mode=ParseMode.HTML
            )
            # Notify user
            try:
                await ctx.bot.send_message(
                    chat_id=target_id,
                    text=f"🚫 <b>Tumhe bot se ban kar diya gaya hai.</b>\n📝 Reason: {escape_html(reason)}",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
        else:
            await update.message.reply_text("❌ User nahi mila.")

    @admin_only
    async def handle_unban(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: <code>/unban user_id</code>", parse_mode=ParseMode.HTML)
            return

        target_id = int(args[0])
        success = await Database.unban_user(target_id)
        if success:
            await update.message.reply_text(f"✅ User {target_id} unban ho gaya.")
            try:
                await ctx.bot.send_message(
                    chat_id=target_id,
                    text="✅ <b>Tumhara ban hata diya gaya.</b> Bot use kar sakte ho ab.",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
        else:
            await update.message.reply_text("❌ User nahi mila.")

    # ─── Channel Management ───────────────────────────────────

    @admin_only
    async def handle_add_channel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: <code>/addchannel @username_or_id Channel Name</code>",
                parse_mode=ParseMode.HTML
            )
            return

        channel_id = args[0]
        channel_name = " ".join(args[1:])
        await Database.add_channel(channel_id, channel_name)
        await update.message.reply_text(
            f"✅ Channel added!\n📢 {escape_html(channel_name)}\n🆔 <code>{channel_id}</code>",
            parse_mode=ParseMode.HTML
        )

    @admin_only
    async def handle_remove_channel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: <code>/removechannel @username_or_id</code>", parse_mode=ParseMode.HTML)
            return

        success = await Database.remove_channel(args[0])
        if success:
            await update.message.reply_text(f"✅ Channel <code>{args[0]}</code> removed.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Channel nahi mila.")

    @admin_only
    async def handle_list_channels(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        channels = await Database.get_force_channels()
        if not channels:
            await update.message.reply_text("📋 Koi force join channel set nahi hai.")
            return

        lines = ["📋 <b>Force Join Channels:</b>\n"]
        for i, ch in enumerate(channels, 1):
            lines.append(f"{i}. {escape_html(ch.get('channel_name', ''))} | <code>{ch['channel_id']}</code>")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    # ─── Limits ───────────────────────────────────────────────

    @admin_only
    async def handle_set_limit(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: <code>/setlimit max_files 500</code> or <code>/setlimit storage_mb 10000</code>",
                parse_mode=ParseMode.HTML
            )
            return

        setting = args[0].lower()
        try:
            value = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Value integer honi chahiye.")
            return

        if setting == "max_files":
            self.cfg.MAX_FILES_PER_USER = value
        elif setting == "storage_mb":
            self.cfg.FREE_STORAGE_MB = value
        elif setting == "upload_rate":
            self.cfg.RATE_LIMIT_UPLOADS_PER_MIN = value
        else:
            await update.message.reply_text("❌ Unknown setting. Options: max_files, storage_mb, upload_rate")
            return

        await update.message.reply_text(f"✅ <code>{setting}</code> set to <b>{value}</b>", parse_mode=ParseMode.HTML)

    # ─── All Users / Files ────────────────────────────────────

    @admin_only
    async def handle_all_users(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        users = await Database.get_all_users()
        count = len(users)
        banned = sum(1 for u in users if u.get("is_banned"))

        lines = [f"👥 <b>All Users ({count}):</b> | Banned: {banned}\n"]
        for u in users[:30]:
            name = escape_html(u.get("first_name") or u.get("username") or str(u["user_id"]))
            ban = "🚫" if u.get("is_banned") else "✅"
            lines.append(f"{ban} <code>{u['user_id']}</code> {name}")

        if count > 30:
            lines.append(f"\n<i>...and {count-30} more</i>")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    @admin_only
    async def handle_all_files(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        total = await Database.count_total_files()
        await update.message.reply_text(
            f"📁 <b>Total Files in System:</b> {total:,}\n\n"
            "Use /search to find specific files.",
            parse_mode=ParseMode.HTML
        )

    # ─── Force Join Toggle ────────────────────────────────────

    @admin_only
    async def handle_toggle_force_join(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        self.cfg.FORCE_JOIN_ENABLED = not self.cfg.FORCE_JOIN_ENABLED
        state = "ON 🟢" if self.cfg.FORCE_JOIN_ENABLED else "OFF 🔴"
        await update.message.reply_text(f"🔐 Force Join is now: <b>{state}</b>", parse_mode=ParseMode.HTML)

    # ─── Maintenance ──────────────────────────────────────────

    @admin_only
    async def handle_maintenance(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        self.cfg.MAINTENANCE_MODE = not self.cfg.MAINTENANCE_MODE
        state = "ON 🔴 (users blocked)" if self.cfg.MAINTENANCE_MODE else "OFF 🟢 (bot running)"
        await update.message.reply_text(f"🔧 Maintenance Mode: <b>{state}</b>", parse_mode=ParseMode.HTML)

    # ─── Logs ─────────────────────────────────────────────────

    @admin_only
    async def handle_logs(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        log_file = "bot.log"
        if os.path.exists(log_file):
            with open(log_file, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="bot.log",
                    caption="📜 Bot logs"
                )
        else:
            # Send last N lines from memory
            await update.message.reply_text("📜 Log file not found. Check Railway logs dashboard.")

    # ─── Bot Info ─────────────────────────────────────────────

    @admin_only
    async def handle_bot_info(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        import sys
        import platform

        bot_info = await ctx.bot.get_me()
        stats = await Database.get_stats()

        text = (
            "ℹ️ <b>Bot Information</b>\n\n"
            f"🤖 <b>Bot:</b> @{bot_info.username}\n"
            f"🆔 <b>Bot ID:</b> <code>{bot_info.id}</code>\n\n"
            f"🐍 <b>Python:</b> {sys.version.split()[0]}\n"
            f"💻 <b>Platform:</b> {platform.system()}\n"
            f"📦 <b>PTB Version:</b> (python-telegram-bot)\n\n"
            f"👥 <b>Users:</b> {stats['total_users']:,}\n"
            f"📁 <b>Files:</b> {stats['total_files']:,}\n"
            f"💾 <b>Storage:</b> {format_size(stats['total_storage_bytes'])}\n\n"
            f"🌐 <b>Webhook:</b> {'Set' if self.cfg.WEBHOOK_URL else 'Polling'}\n"
            f"📢 <b>Storage Channel:</b> <code>{self.cfg.STORAGE_CHANNEL_ID}</code>\n"
            f"🔐 <b>Force Join:</b> {'ON' if self.cfg.FORCE_JOIN_ENABLED else 'OFF'}\n"
            f"🔧 <b>Maintenance:</b> {'ON' if self.cfg.MAINTENANCE_MODE else 'OFF'}"
        )

        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    # ─── Admin Callbacks ──────────────────────────────────────

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        user = q.from_user
        if not self.cfg.is_admin(user.id):
            await q.answer("Admin only!", show_alert=True)
            return

        await q.answer()
        data = q.data

        if data == "admin_stats":
            stats = await Database.get_stats()
            text = (
                "📊 <b>Full Statistics</b>\n\n"
                f"👥 Total Users: {stats['total_users']:,}\n"
                f"🟢 Active Today: {stats['active_today']:,}\n"
                f"📁 Total Files: {stats['total_files']:,}\n"
                f"💾 Storage: {format_size(stats['total_storage_bytes'])}\n\n"
                f"📤 Today Uploads: {stats['today_uploads']:,}\n"
                f"📥 Today Downloads: {stats['today_downloads']:,}"
            )
            await q.message.reply_text(text, parse_mode=ParseMode.HTML)

        elif data == "admin_channels":
            ctx.args = []
            update._effective_message = q.message
            await self.handle_list_channels(update, ctx)

        elif data == "admin_forcejoin":
            update._effective_message = q.message
            await self.handle_toggle_force_join(update, ctx)

        elif data == "admin_maintenance":
            update._effective_message = q.message
            await self.handle_maintenance(update, ctx)

        elif data == "admin_botinfo":
            update._effective_message = q.message
            await self.handle_bot_info(update, ctx)

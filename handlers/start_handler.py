"""
Start Handler — /start, /help, /profile, /stats, /referral, /leaderboard
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import Config
from database.mongodb import Database
from middlewares.force_join import ForceJoinMiddleware
from utils.helpers import format_size, escape_html

logger = logging.getLogger(__name__)


class StartHandler:

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.force_join = ForceJoinMiddleware(cfg)

    # ─── /start ───────────────────────────────────────────────

    async def handle_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user:
            return

        # Check maintenance mode
        if self.cfg.MAINTENANCE_MODE and not self.cfg.is_admin(user.id):
            await update.message.reply_text(
                "🔧 <b>Bot maintenance chal raha hai.</b>\n\nThodi der mein wapis aao. 🙏",
                parse_mode="HTML"
            )
            return

        # Parse referral from deep link: /start ref_XXXX
        referral_by: Optional[int] = None
        args = ctx.args
        if args:
            arg = args[0]
            if arg.startswith("ref_"):
                ref_code = arg[4:]
                ref_user = await Database.get_user_by_referral_code(ref_code)
                if ref_user and ref_user["user_id"] != user.id:
                    referral_by = ref_user["user_id"]
            elif arg.startswith("get_"):
                # Deep link for file: /start get_FILEKEY
                file_key = arg[4:]
                await self._handle_deep_link_file(update, ctx, file_key)
                return

        # Register user
        db_user = await Database.add_user(
            user.id,
            user.username or "",
            user.first_name or "User",
            referral_by=referral_by
        )

        # Ban check
        if db_user.get("is_banned"):
            await update.message.reply_text(
                "🚫 <b>Tumhe ban kar diya gaya hai.</b>\n\n"
                f"Support ke liye contact karo: @{self.cfg.SUPPORT_USERNAME}" if self.cfg.SUPPORT_USERNAME else "🚫 <b>You are banned.</b>",
                parse_mode="HTML"
            )
            return

        # Force join check
        all_joined, not_joined = await self.force_join.check_membership(ctx.bot, user.id)
        if not all_joined:
            await self.force_join.send_join_request(ctx.bot, update.effective_chat.id, not_joined)
            return

        # Welcome message
        buttons = [
            [
                InlineKeyboardButton("📤 Upload File", callback_data="start_upload_help"),
                InlineKeyboardButton("📁 My Files", callback_data="start_myfiles"),
            ],
            [
                InlineKeyboardButton("🔗 Get by Link", callback_data="start_getlink"),
                InlineKeyboardButton("👤 Profile", callback_data="start_profile"),
            ],
            [
                InlineKeyboardButton("📊 Stats", callback_data="start_stats"),
                InlineKeyboardButton("🏆 Leaderboard", callback_data="start_leaderboard"),
            ],
            [InlineKeyboardButton("❓ Help", callback_data="start_help")],
        ]
        markup = InlineKeyboardMarkup(buttons)

        welcome = (
            f"👋 <b>Welcome, {escape_html(user.first_name)}!</b>\n\n"
            f"🗄️ <b>{self.cfg.BOT_NAME}</b> — Advanced File Share Bot\n\n"
            "✅ <b>Kya kar sakte ho:</b>\n"
            "• Unlimited files upload karo\n"
            "• Files ko password se lock karo 🔐\n"
            "• Secure share links generate karo 🔗\n"
            "• Files search karo 🔍\n"
            "• Referral earn karo 🎁\n\n"
            "<i>Koi bhi file bhejo ya neeche se option chuno 👇</i>"
        )

        if referral_by:
            welcome += "\n\n🎁 <b>Referral se join kiya — dono ko bonus milega!</b>"

        await update.message.reply_text(welcome, reply_markup=markup, parse_mode="HTML")

    async def _handle_deep_link_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, file_key: str) -> None:
        """Handle /start get_FILEKEY deep links."""
        from handlers.file_handler import FileHandler
        fh = FileHandler(self.cfg)

        user = update.effective_user
        db_user = await Database.get_user(user.id)
        if not db_user:
            db_user = await Database.add_user(user.id, user.username or "", user.first_name or "")

        if db_user.get("is_banned"):
            await update.message.reply_text("🚫 You are banned.")
            return

        # Force join
        all_joined, not_joined = await self.force_join.check_membership(ctx.bot, user.id)
        if not all_joined:
            await self.force_join.send_join_request(ctx.bot, update.effective_chat.id, not_joined)
            return

        await fh._deliver_file(update, ctx, file_key)

    # ─── /help ────────────────────────────────────────────────

    async def handle_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        text = (
            "📖 <b>Commands List</b>\n\n"
            "<b>📁 File Commands:</b>\n"
            "/get <code>file_key</code> — File retrieve karo\n"
            "/myfiles — Apni files dekho\n"
            "/delete <code>file_key</code> — File delete karo\n"
            "/rename <code>file_key new_name</code> — Rename karo\n"
            "/lock <code>file_key password</code> — File ko lock karo\n"
            "/unlock <code>file_key</code> — Lock hatao\n"
            "/share <code>file_key</code> — Share link banao\n"
            "/info <code>file_key</code> — File info dekho\n"
            "/search <code>query</code> — Files search karo\n\n"
            "<b>👤 User Commands:</b>\n"
            "/start — Bot start karo\n"
            "/profile — Apna profile dekho\n"
            "/stats — Bot statistics\n"
            "/referral — Referral link lo\n"
            "/leaderboard — Top referrers\n"
            "/help — Yeh message\n\n"
            "<b>📤 Upload:</b>\n"
            "Koi bhi file seedha bhejo — document, video, audio, photo sab!\n\n"
            "<b>🔗 Share Link:</b>\n"
            f"Format: <code>https://t.me/{self.cfg.BOT_USERNAME}?start=get_FILE_KEY</code>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    # ─── /profile ─────────────────────────────────────────────

    async def handle_profile(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        db_user = await Database.get_user(user.id)
        if not db_user:
            await update.message.reply_text("Pehle /start karo.")
            return

        total_files = await Database.count_user_files(user.id)
        storage = format_size(db_user.get("storage_used_bytes", 0))
        plan = db_user.get("plan", "free").upper()

        text = (
            f"👤 <b>Your Profile</b>\n\n"
            f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
            f"📛 <b>Name:</b> {escape_html(db_user.get('first_name', ''))}\n"
            f"👤 <b>Username:</b> @{db_user.get('username') or 'N/A'}\n"
            f"💎 <b>Plan:</b> {plan}\n\n"
            f"📁 <b>Total Files:</b> {total_files}\n"
            f"💾 <b>Storage Used:</b> {storage}\n"
            f"📤 <b>Total Uploads:</b> {db_user.get('total_uploads', 0)}\n"
            f"📥 <b>Total Downloads:</b> {db_user.get('total_downloads', 0)}\n"
            f"👥 <b>Referrals:</b> {db_user.get('referral_count', 0)}\n"
            f"📅 <b>Joined:</b> {db_user['joined_at'].strftime('%d %b %Y')}\n"
        )

        ref_code = db_user.get("referral_code", "")
        if ref_code and self.cfg.BOT_USERNAME:
            ref_link = f"https://t.me/{self.cfg.BOT_USERNAME}?start=ref_{ref_code}"
            text += f"\n🔗 <b>Referral Link:</b>\n<code>{ref_link}</code>"

        await update.message.reply_text(text, parse_mode="HTML")

    # ─── /stats ───────────────────────────────────────────────

    async def handle_stats(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        stats = await Database.get_stats()
        text = (
            "📊 <b>Bot Statistics</b>\n\n"
            f"👥 <b>Total Users:</b> {stats['total_users']:,}\n"
            f"🟢 <b>Active Today:</b> {stats['active_today']:,}\n"
            f"📁 <b>Total Files:</b> {stats['total_files']:,}\n"
            f"💾 <b>Total Storage:</b> {format_size(stats['total_storage_bytes'])}\n\n"
            f"📤 <b>Today Uploads:</b> {stats['today_uploads']:,}\n"
            f"📥 <b>Today Downloads:</b> {stats['today_downloads']:,}\n"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    # ─── /referral ────────────────────────────────────────────

    async def handle_referral(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        db_user = await Database.get_user(user.id)
        if not db_user:
            await update.message.reply_text("Pehle /start karo.")
            return

        ref_code = db_user.get("referral_code", "")
        ref_count = db_user.get("referral_count", 0)

        if not self.cfg.BOT_USERNAME:
            await update.message.reply_text("Bot username set nahi hai admin se bolo.")
            return

        ref_link = f"https://t.me/{self.cfg.BOT_USERNAME}?start=ref_{ref_code}"
        text = (
            "🎁 <b>Referral Program</b>\n\n"
            f"👥 <b>Tumne refer kiya:</b> {ref_count} log\n\n"
            f"🔗 <b>Tera Referral Link:</b>\n<code>{ref_link}</code>\n\n"
            "Share karo aur bonus pao! 🏆"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    # ─── /leaderboard ─────────────────────────────────────────

    async def handle_leaderboard(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        leaders = await Database.get_referral_leaderboard(10)
        if not leaders:
            await update.message.reply_text("Abhi koi leaderboard data nahi hai.")
            return

        lines = ["🏆 <b>Referral Leaderboard</b>\n"]
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        for i, u in enumerate(leaders):
            name = escape_html(u.get("first_name", "User"))
            count = u.get("referral_count", 0)
            lines.append(f"{medals[i]} {name} — <b>{count}</b> referrals")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    # ─── Inline Callbacks ─────────────────────────────────────

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        await q.answer()
        data = q.data

        if data == "start_profile":
            update._effective_message = q.message
            await self.handle_profile(update, ctx)
        elif data == "start_stats":
            update._effective_message = q.message
            await self.handle_stats(update, ctx)
        elif data == "start_leaderboard":
            update._effective_message = q.message
            await self.handle_leaderboard(update, ctx)
        elif data == "start_help":
            update._effective_message = q.message
            await self.handle_help(update, ctx)
        elif data == "start_upload_help":
            await q.message.reply_text(
                "📤 <b>File Upload Karo</b>\n\n"
                "Seedha koi bhi file bhejo is chat mein!\n\n"
                "✅ <b>Supported:</b> Documents, Videos, Audio, Photos, Stickers, Voice\n"
                f"📏 <b>Max Size:</b> {self.cfg.MAX_FILE_SIZE_MB} MB\n\n"
                "File upload hone ke baad tumhe ek unique file key aur share link milega 🔗",
                parse_mode="HTML"
            )
        elif data == "start_myfiles":
            ctx.args = []
            await ctx.bot.send_message(
                chat_id=q.message.chat_id,
                text="📁 /myfiles — Tumhari files load ho rahi hain..."
            )

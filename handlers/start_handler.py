"""
╔══════════════════════════════════════════════════════════════╗
║               ULTRA VIP START HANDLER SYSTEM                 ║
║       God Mode | Unicode Bold Buttons | Zero Lag Engine      ║
╚══════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import logging
import asyncio
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from config import Config
from database.mongodb import Database
from middlewares.force_join import ForceJoinMiddleware
from utils.helpers import format_size, escape_html

# ─── System Logger ───────────────────────────────────────────
logger = logging.getLogger(__name__)

class StartHandler:
    """Master controller for Start, Help, Profile, Stats, and Callbacks."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.force_join = ForceJoinMiddleware(cfg)
        logger.info("⚡ StartHandler Loaded Successfully.")

    # ═════════════════════════════════════════════════════════════
    # 💎 /start COMMAND MASTER LOGIC
    # ═════════════════════════════════════════════════════════════

    async def handle_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles the main /start command and deep links."""
        user = update.effective_user
        msg = update.effective_message
        if not user or not msg:
            return

        # 🛠️ 1. MAINTENANCE MODE CHECK
        if self.cfg.MAINTENANCE_MODE and not self.cfg.is_admin(user.id):
            await msg.reply_text(
                "⚠️ <b>System Upgrade in Progress</b>\n\n"
                "Bot abhi maintenance mode mein hai. Thodi der mein wapis aana. 🙏",
                parse_mode="HTML"
            )
            return

        # 🔗 2. DEEP LINK PARSING (/start ref_XYZ or /start get_XYZ)
        referral_by: Optional[int] = None
        args = ctx.args
        if args:
            arg = args[0]
            if arg.startswith("ref_"):
                ref_code = arg[4:]
                ref_user = await Database.get_user_by_referral_code(ref_code)
                if ref_user and ref_user["user_id"] != user.id:
                    referral_by = ref_user["user_id"]
                    logger.info(f"🎁 Referral detected: {user.id} referred by {referral_by}")
            elif arg.startswith("get_"):
                # Handle direct file fetch
                file_key = arg[4:]
                await self._handle_deep_link_file(update, ctx, file_key)
                return

        # 🗄️ 3. DATABASE REGISTRATION
        db_user = await Database.add_user(
            user.id,
            user.username or "",
            user.first_name or "VIP User",
            referral_by=referral_by
        )

        # 🚫 4. BAN SYSTEM CHECK
        if db_user.get("is_banned"):
            support = f"@{self.cfg.SUPPORT_USERNAME}" if getattr(self.cfg, 'SUPPORT_USERNAME', None) else "Admins"
            await msg.reply_text(
                "🚫 <b>Account Suspended</b>\n\n"
                f"Tumhare account ko ban kar diya gaya hai. Contact: {support}",
                parse_mode="HTML"
            )
            return

        # 🔒 5. FORCE JOIN VERIFICATION
        all_joined, not_joined = await self.force_join.check_membership(ctx.bot, user.id)
        if not all_joined:
            await self.force_join.send_join_request(ctx.bot, update.effective_chat.id, not_joined)
            return

        # 🎮 6. VIP DASHBOARD UI (The Bold Unicode Magic)
        buttons = [
            [
                InlineKeyboardButton("𝗨𝗽𝗹𝗼𝗮𝗱 𝗙𝗶𝗹𝗲", callback_data="start_upload_help"),
                InlineKeyboardButton("𝗠𝘆 𝗙𝗶𝗹𝗲𝘀", callback_data="start_myfiles"),
            ],
            [
                InlineKeyboardButton("𝗚𝗲𝘁 𝗕𝘆 𝗟𝗶𝗻𝗸", callback_data="start_getlink"),
                InlineKeyboardButton("𝗣𝗿𝗼𝗳𝗶𝗹𝗲", callback_data="start_profile"),
            ],
            [
                InlineKeyboardButton("𝗦𝘁𝗮𝘁𝘀", callback_data="start_stats"),
                InlineKeyboardButton("𝗟𝗲𝗮𝗱𝗲𝗿𝗯𝗼𝗮𝗿𝗱", callback_data="start_leaderboard"),
            ],
            [
                InlineKeyboardButton("𝗛𝗲𝗹𝗽 𝗖𝗲𝗻𝘁𝗲𝗿", callback_data="start_help")
            ],
        ]
        markup = InlineKeyboardMarkup(buttons)

        # Typing Action show karo taaki premium feel aaye
        await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        await asyncio.sleep(0.3)

        welcome_text = (
            f"👋 <b>Welcome to the Elite Network, {escape_html(user.first_name)}!</b>\n\n"
            f"⚡ <b>{self.cfg.BOT_NAME}</b> is your ultimate storage powerhouse.\n\n"
            "💎 <b>VIP Features You Can Use:</b>\n"
            "• Upload unlimited files securely\n"
            "• Add robust passwords to your files 🔐\n"
            "• Generate lightning-fast share links 🔗\n"
            "• Earn exclusive rewards via Referrals 🎁\n\n"
            "<i>Choose an option below or directly send a file to begin. 👇</i>"
        )

        if referral_by:
            welcome_text += "\n\n🎉 <b>Referral Bonus Activated! Both you and your friend earned points.</b>"

        await msg.reply_text(welcome_text, reply_markup=markup, parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════
    # 🔗 DEEP LINK FILE FETCHING LOGIC
    # ═════════════════════════════════════════════════════════════

    async def _handle_deep_link_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, file_key: str) -> None:
        """Processes /start get_FILEKEY and delivers the file instantly."""
        from handlers.file_handler import FileHandler
        fh = FileHandler(self.cfg)

        user = update.effective_user
        msg = update.effective_message
        db_user = await Database.get_user(user.id)
        
        # Fallback registration
        if not db_user:
            db_user = await Database.add_user(user.id, user.username or "", user.first_name or "VIP User")

        if db_user.get("is_banned"):
            await msg.reply_text("🚫 <b>Access Denied: Account Banned.</b>", parse_mode="HTML")
            return

        all_joined, not_joined = await self.force_join.check_membership(ctx.bot, user.id)
        if not all_joined:
            await self.force_join.send_join_request(ctx.bot, update.effective_chat.id, not_joined)
            return

        # Delivery logic inside file handler
        await fh._deliver_file(update, ctx, file_key)

    # ═════════════════════════════════════════════════════════════
    # 📖 /help COMMAND
    # ═════════════════════════════════════════════════════════════

    async def handle_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        help_text = (
            "📖 <b>Master Command Directory</b>\n\n"
            "<b>📁 Core File Management:</b>\n"
            "• <code>/get file_key</code> — Fetch a specific file\n"
            "• <code>/myfiles</code> — View your personal vault\n"
            "• <code>/delete file_key</code> — Permanently remove a file\n"
            "• <code>/rename file_key new_name</code> — Rename your file\n"
            "• <code>/lock file_key password</code> — Secure file with password\n"
            "• <code>/unlock file_key</code> — Remove password protection\n"
            "• <code>/share file_key</code> — Generate sharing link\n"
            "• <code>/info file_key</code> — Inspect file details\n"
            "• <code>/search query</code> — Search your uploads\n\n"
            "<b>👤 Account Controls:</b>\n"
            "• <code>/start</code> — Reboot the system\n"
            "• <code>/profile</code> — View your account stats\n"
            "• <code>/stats</code> — View global bot statistics\n"
            "• <code>/referral</code> — Get your money-making link\n"
            "• <code>/leaderboard</code> — View top referrers\n\n"
            "<b>📤 How to Upload?</b>\n"
            "Simply send or forward ANY file (Video, Document, Photo, Audio) directly to this chat.\n\n"
            "<b>🔗 Share Format:</b>\n"
            f"<code>https://t.me/{self.cfg.BOT_USERNAME}?start=get_YOUR_KEY</code>"
        )
        await msg.reply_text(help_text, parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════
    # 👤 /profile COMMAND
    # ═════════════════════════════════════════════════════════════

    async def handle_profile(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        msg = update.effective_message
        db_user = await Database.get_user(user.id)
        
        if not db_user:
            await msg.reply_text("⚠️ Database error. Please hit /start first.")
            return

        total_files = await Database.count_user_files(user.id)
        storage = format_size(db_user.get("storage_used_bytes", 0))
        plan = db_user.get("plan", "VIP PRO").upper()

        profile_text = (
            f"👤 <b>Your Elite Profile</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
            f"📛 <b>Name:</b> {escape_html(db_user.get('first_name', 'VIP'))}\n"
            f"👤 <b>Username:</b> @{db_user.get('username') or 'Hidden'}\n"
            f"💎 <b>Status:</b> <b>{plan}</b>\n\n"
            f"📁 <b>Vault Files:</b> {total_files}\n"
            f"💾 <b>Storage Consumed:</b> {storage}\n"
            f"📤 <b>Cloud Uploads:</b> {db_user.get('total_uploads', 0)}\n"
            f"📥 <b>Cloud Downloads:</b> {db_user.get('total_downloads', 0)}\n"
            f"👥 <b>Active Referrals:</b> {db_user.get('referral_count', 0)}\n"
            f"📅 <b>Member Since:</b> {db_user['joined_at'].strftime('%d %B %Y')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
        )

        ref_code = db_user.get("referral_code", "")
        if ref_code and self.cfg.BOT_USERNAME:
            ref_link = f"https://t.me/{self.cfg.BOT_USERNAME}?start=ref_{ref_code}"
            profile_text += f"\n🔗 <b>Your Invite Link:</b>\n<code>{ref_link}</code>"

        await msg.reply_text(profile_text, parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════
    # 📊 /stats COMMAND
    # ═════════════════════════════════════════════════════════════

    async def handle_stats(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        stats = await Database.get_stats()
        stats_text = (
            "📊 <b>Global Network Statistics</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Total Citizens:</b> {stats['total_users']:,}\n"
            f"🟢 <b>Online Today:</b> {stats['active_today']:,}\n"
            f"📁 <b>Global Files:</b> {stats['total_files']:,}\n"
            f"💾 <b>Server Storage:</b> {format_size(stats['total_storage_bytes'])}\n\n"
            f"📤 <b>Today's Traffic (IN):</b> {stats['today_uploads']:,}\n"
            f"📥 <b>Today's Traffic (OUT):</b> {stats['today_downloads']:,}\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )
        await msg.reply_text(stats_text, parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════
    # 🎁 /referral COMMAND
    # ═════════════════════════════════════════════════════════════

    async def handle_referral(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        msg = update.effective_message
        db_user = await Database.get_user(user.id)
        if not db_user:
            await msg.reply_text("Please trigger /start to initialize your account.")
            return

        ref_code = db_user.get("referral_code", "")
        ref_count = db_user.get("referral_count", 0)

        if not self.cfg.BOT_USERNAME:
            await msg.reply_text("System Error: Bot username missing.")
            return

        ref_link = f"https://t.me/{self.cfg.BOT_USERNAME}?start=ref_{ref_code}"
        ref_text = (
            "🎁 <b>VIP Referral Program</b>\n\n"
            f"👥 <b>Your Successful Invites:</b> {ref_count}\n\n"
            f"🔗 <b>Your Exclusive Link:</b>\n<code>{ref_link}</code>\n\n"
            "<i>Share this link to earn extra storage and VIP perks!</i> 🏆"
        )
        await msg.reply_text(ref_text, parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════
    # 🏆 /leaderboard COMMAND
    # ═════════════════════════════════════════════════════════════

    async def handle_leaderboard(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        leaders = await Database.get_referral_leaderboard(10)
        if not leaders:
            await msg.reply_text("🏆 No one has claimed the throne yet.")
            return

        lines = ["🏆 <b>Top Network Influencers</b>\n"]
        medals = ["🥇", "🥈", "🥉", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅"]
        
        for i, u in enumerate(leaders):
            name = escape_html(u.get("first_name", "VIP"))
            count = u.get("referral_count", 0)
            lines.append(f"{medals[i]} {name} — <b>{count} points</b>")

        await msg.reply_text("\n".join(lines), parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════
    # ⚙️ LIGHTNING FAST CALLBACK ENGINE
    # ═════════════════════════════════════════════════════════════

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        
        try:
            await q.answer()
        except Exception as e:
            logger.warning(f"Failed to answer callback query: {e}")
            return

        data = q.data

        try:
            # Re-routing with safe effective_message propagation
            if data == "start_profile":
                await self.handle_profile(update, ctx)
                
            elif data == "start_stats":
                await self.handle_stats(update, ctx)
                
            elif data == "start_leaderboard":
                await self.handle_leaderboard(update, ctx)
                
            elif data == "start_help":
                await self.handle_help(update, ctx)
                
            elif data == "start_upload_help":
                await q.message.reply_text(
                    "📤 <b>File Upload Protocol</b>\n\n"
                    "Send or forward ANY file here instantly.\n\n"
                    "✅ <b>Supported Formats:</b> Documents, Videos, Audio, Photos, Stickers, Archives.\n"
                    f"📏 <b>Limit:</b> {self.cfg.MAX_FILE_SIZE_MB} MB\n\n"
                    "<i>Once processed, you will receive an encrypted vault key and share link.</i>",
                    parse_mode="HTML"
                )
                
            elif data == "start_myfiles":
                ctx.args = []
                await ctx.bot.send_message(
                    chat_id=q.message.chat_id,
                    text="📁 <b>Accessing Vault...</b>\nType /myfiles to view your inventory.",
                    parse_mode="HTML"
                )
                
            elif data == "start_getlink":
                await q.message.reply_text(
                    "🔗 <b>Link Fetcher</b>\n\n"
                    "Agar tumhare paas file key hai, toh bas chat mein `/get FILE_KEY` likho.",
                    parse_mode="HTML"
                )
                
            else:
                logger.warning(f"Unknown callback data received: {data}")
                
        except Exception as e:
            logger.error(f"Error executing callback action for {data}: {e}", exc_info=True)
            await q.message.reply_text("⚠️ Request timeout. Please use command directly.", parse_mode="HTML")

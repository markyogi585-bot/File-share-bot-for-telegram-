"""
File Handler — Upload, Download, Lock, Share, Search, Rename, Delete
The core feature set of the bot.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from config import Config
from database.mongodb import Database
from middlewares.force_join import ForceJoinMiddleware
from middlewares.rate_limiter import RateLimiter
from utils.encryption import Encryptor
from utils.helpers import format_size, escape_html, get_file_type_emoji

logger = logging.getLogger(__name__)

# Shared rate limiter & encryptor instances (created once in app)
_rate_limiter: Optional[RateLimiter] = None
_encryptor: Optional[Encryptor] = None


def get_rate_limiter(cfg: Config) -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(cfg)
    return _rate_limiter


def get_encryptor(cfg: Config) -> Encryptor:
    global _encryptor
    if _encryptor is None:
        _encryptor = Encryptor(cfg.ENCRYPTION_KEY)
    return _encryptor


class FileHandler:

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.force_join = ForceJoinMiddleware(cfg)
        self.enc = get_encryptor(cfg)
        self.rl = get_rate_limiter(cfg)

    # ─── Guard: Check user ────────────────────────────────────

    async def _guard(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> Optional[dict]:
        """Returns db_user if all checks pass, else None."""
        user = update.effective_user
        if not user:
            return None

        if self.cfg.MAINTENANCE_MODE and not self.cfg.is_admin(user.id):
            await update.effective_message.reply_text("🔧 Bot maintenance mode mein hai. Baad mein aao.")
            return None

        db_user = await Database.get_user(user.id)
        if not db_user:
            db_user = await Database.add_user(user.id, user.username or "", user.first_name or "")

        if db_user.get("is_banned"):
            await update.effective_message.reply_text("🚫 Tumhe ban kar diya gaya hai.")
            return None

        # Force join
        all_joined, not_joined = await self.force_join.check_membership(ctx.bot, user.id)
        if not all_joined:
            await self.force_join.send_join_request(ctx.bot, update.effective_chat.id, not_joined)
            return None

        return db_user

    # ─── Upload ───────────────────────────────────────────────

    async def handle_upload(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        db_user = await self._guard(update, ctx)
        if not db_user:
            return

        user = update.effective_user
        msg: Message = update.effective_message

        # Rate limit check
        if not self.rl.check(user.id, "upload"):
            wait = self.rl.get_wait_time(user.id, "upload")
            await msg.reply_text(f"⏳ Thoda rukko! {wait}s baad try karo (rate limit).")
            return

        # File limit check
        current_count = await Database.count_user_files(user.id)
        if current_count >= self.cfg.MAX_FILES_PER_USER and not self.cfg.is_admin(user.id):
            await msg.reply_text(
                f"📦 Storage full! Max {self.cfg.MAX_FILES_PER_USER} files allowed.\n"
                "Purani files /delete se hatao."
            )
            return

        # Extract file info from any media type
        file_info = self._extract_file_info(msg)
        if not file_info:
            return  # Not a file message

        tg_file_id, file_name, file_size, file_type = file_info

        # Size check
        max_bytes = self.cfg.MAX_FILE_SIZE_MB * 1024 * 1024
        if file_size and file_size > max_bytes:
            await msg.reply_text(
                f"❌ File bahut badi hai! Max size: {self.cfg.MAX_FILE_SIZE_MB} MB\n"
                f"Teri file: {format_size(file_size)}"
            )
            return

        # Forward to storage channel
        processing_msg = await msg.reply_text("⬆️ Uploading...")

        try:
            stored_msg = await ctx.bot.forward_message(
                chat_id=self.cfg.STORAGE_CHANNEL_ID,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id
            )
        except TelegramError as e:
            logger.error(f"Storage channel forward failed: {e}")
            await processing_msg.edit_text("❌ Upload failed! Storage channel error. Admin ko batao.")
            return

        # Generate file key
        file_key = self.enc.generate_file_key()

        # Extract caption/tags from message caption
        caption = msg.caption or ""
        tags = [w.lstrip("#").lower() for w in caption.split() if w.startswith("#")]

        # Save to DB
        await Database.save_file(
            file_key=file_key,
            owner_id=user.id,
            file_id=tg_file_id,
            file_name=file_name,
            file_size=file_size or 0,
            file_type=file_type,
            message_id=stored_msg.message_id,
            tags=tags,
            caption=caption,
        )

        # Build share link
        bot_username = self.cfg.BOT_USERNAME
        share_link = f"https://t.me/{bot_username}?start=get_{file_key}" if bot_username else None
        emoji = get_file_type_emoji(file_type)

        buttons = [
            [InlineKeyboardButton("🔗 Share Link", callback_data=f"file_share_{file_key}")],
            [
                InlineKeyboardButton("🔐 Lock File", callback_data=f"file_lock_{file_key}"),
                InlineKeyboardButton("❌ Delete", callback_data=f"file_delete_{file_key}"),
            ],
            [InlineKeyboardButton("📋 File Info", callback_data=f"file_info_{file_key}")],
        ]
        markup = InlineKeyboardMarkup(buttons)

        result_text = (
            f"{emoji} <b>File Uploaded!</b>\n\n"
            f"📄 <b>Name:</b> {escape_html(file_name)}\n"
            f"💾 <b>Size:</b> {format_size(file_size or 0)}\n"
            f"🔑 <b>Key:</b> <code>{file_key}</code>\n"
        )
        if share_link:
            result_text += f"\n🔗 <b>Share Link:</b>\n<code>{share_link}</code>"

        await processing_msg.edit_text(result_text, reply_markup=markup, parse_mode=ParseMode.HTML)

        # Auto delete if configured
        if self.cfg.AUTO_DELETE_SECONDS > 0:
            import asyncio
            async def _auto_del():
                await asyncio.sleep(self.cfg.AUTO_DELETE_SECONDS)
                try:
                    await processing_msg.delete()
                except Exception:
                    pass
            ctx.application.create_task(_auto_del())

    def _extract_file_info(self, msg: Message):
        """Extract (file_id, file_name, file_size, file_type) from message."""
        if msg.document:
            f = msg.document
            return f.file_id, f.file_name or "document", f.file_size, "document"
        elif msg.video:
            f = msg.video
            name = f.file_name or f"video_{f.file_id[:8]}.mp4"
            return f.file_id, name, f.file_size, "video"
        elif msg.audio:
            f = msg.audio
            name = f.file_name or f"{f.performer or 'audio'} - {f.title or 'track'}.mp3"
            return f.file_id, name, f.file_size, "audio"
        elif msg.photo:
            f = msg.photo[-1]  # Largest size
            return f.file_id, f"photo_{f.file_id[:8]}.jpg", f.file_size, "photo"
        elif msg.sticker:
            f = msg.sticker
            return f.file_id, f"sticker_{f.file_id[:8]}", f.file_size, "sticker"
        elif msg.voice:
            f = msg.voice
            return f.file_id, f"voice_{f.file_id[:8]}.ogg", f.file_size, "voice"
        elif msg.video_note:
            f = msg.video_note
            return f.file_id, f"videonote_{f.file_id[:8]}.mp4", f.file_size, "video_note"
        elif msg.animation:
            f = msg.animation
            return f.file_id, f.file_name or f"animation_{f.file_id[:8]}.gif", f.file_size, "animation"
        return None

    # ─── Get File ─────────────────────────────────────────────

    async def handle_get_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /get file_key"""
        db_user = await self._guard(update, ctx)
        if not db_user:
            return

        args = ctx.args
        if not args:
            await update.message.reply_text(
                "Usage: <code>/get file_key</code>\n\nFile key upload ke baad milti hai.",
                parse_mode=ParseMode.HTML
            )
            return

        file_key = args[0].strip()
        await self._deliver_file(update, ctx, file_key)

    async def _deliver_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, file_key: str) -> None:
        """Core delivery logic — also used by deep links."""
        user = update.effective_user
        msg = update.effective_message

        file_doc = await Database.get_file(file_key)
        if not file_doc:
            await msg.reply_text("❌ File nahi mili ya delete ho gayi. File key check karo.")
            return

        # Rate limit
        if not self.rl.check(user.id, "download"):
            wait = self.rl.get_wait_time(user.id, "download")
            await msg.reply_text(f"⏳ Download rate limit! {wait}s baad try karo.")
            return

        # Encryption check
        if file_doc.get("is_encrypted") and file_doc.get("password_hash"):
            ctx.user_data["pending_file_key"] = file_key
            await msg.reply_text(
                "🔐 <b>File Locked!</b>\n\nPassword bhejo unlock karne ke liye:",
                parse_mode=ParseMode.HTML
            )
            ctx.user_data["awaiting_password"] = True
            return

        await self._send_file_from_storage(msg, ctx, file_doc)

    async def _send_file_from_storage(self, msg: Message, ctx: ContextTypes.DEFAULT_TYPE, file_doc: dict) -> None:
        """Forward file from storage channel to user."""
        try:
            sent = await ctx.bot.copy_message(
                chat_id=msg.chat_id,
                from_chat_id=self.cfg.STORAGE_CHANNEL_ID,
                message_id=file_doc["message_id"],
                caption=file_doc.get("caption") or f"📄 {file_doc['file_name']}",
            )
            await Database.increment_download(file_doc["file_key"])

            info_btn = [[InlineKeyboardButton("📋 File Info", callback_data=f"file_info_{file_doc['file_key']}")]]
            await msg.reply_text(
                f"✅ <b>File delivered!</b>\n📄 {escape_html(file_doc['file_name'])}\n💾 {format_size(file_doc.get('file_size',0))}",
                reply_markup=InlineKeyboardMarkup(info_btn),
                parse_mode=ParseMode.HTML
            )
        except TelegramError as e:
            logger.error(f"Deliver file error: {e}")
            await msg.reply_text("❌ File deliver nahi hui. Storage channel check karo.")

    # ─── My Files ─────────────────────────────────────────────

    async def handle_my_files(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        db_user = await self._guard(update, ctx)
        if not db_user:
            return

        user = update.effective_user
        args = ctx.args
        page = 1
        if args and args[0].isdigit():
            page = max(1, int(args[0]))

        per_page = 8
        files = await Database.get_user_files(user.id, page=page, per_page=per_page)
        total = await Database.count_user_files(user.id)
        total_pages = max(1, math.ceil(total / per_page))

        if not files:
            await update.message.reply_text(
                "📁 <b>Koi file nahi mili!</b>\n\nKoi bhi file bhejo upload karne ke liye.",
                parse_mode=ParseMode.HTML
            )
            return

        lines = [f"📁 <b>Tumhari Files</b> (Page {page}/{total_pages}, Total: {total})\n"]
        for i, f in enumerate(files, 1):
            emoji = get_file_type_emoji(f.get("file_type", ""))
            locked = "🔐" if f.get("is_encrypted") else ""
            name = escape_html(f["file_name"][:40])
            size = format_size(f.get("file_size", 0))
            dl = f.get("download_count", 0)
            lines.append(f"{(page-1)*per_page+i}. {emoji}{locked} <code>{f['file_key']}</code>\n   📄 {name} | {size} | ⬇️{dl}")

        text = "\n".join(lines)

        # Pagination buttons
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"file_myfiles_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"file_myfiles_{page+1}"))

        markup = InlineKeyboardMarkup([nav_buttons] if nav_buttons else [])
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)

    # ─── Delete ───────────────────────────────────────────────

    async def handle_delete_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        db_user = await self._guard(update, ctx)
        if not db_user:
            return

        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: <code>/delete file_key</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0]
        success = await Database.delete_file(file_key, update.effective_user.id)
        if success:
            await update.message.reply_text(f"✅ File <code>{file_key}</code> delete ho gayi.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ File nahi mili ya permission nahi hai.")

    # ─── Rename ───────────────────────────────────────────────

    async def handle_rename_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        db_user = await self._guard(update, ctx)
        if not db_user:
            return

        args = ctx.args
        if len(args) < 2:
            await update.message.reply_text("Usage: <code>/rename file_key new_name</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0]
        new_name = " ".join(args[1:])
        success = await Database.rename_file(file_key, update.effective_user.id, new_name)
        if success:
            await update.message.reply_text(f"✅ Renamed to: <code>{escape_html(new_name)}</code>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ File nahi mili ya permission nahi hai.")

    # ─── Lock / Unlock ────────────────────────────────────────

    async def handle_lock_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        db_user = await self._guard(update, ctx)
        if not db_user:
            return

        args = ctx.args
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: <code>/lock file_key password</code>\n\n⚠️ Password yaad rakhna — reset nahi hoga!",
                parse_mode=ParseMode.HTML
            )
            return

        file_key = args[0]
        password = " ".join(args[1:])

        if len(password) < 4:
            await update.message.reply_text("❌ Password minimum 4 characters ka hona chahiye.")
            return

        enc = get_encryptor(self.cfg)
        password_hash = enc.hash_password(password)
        success = await Database.set_file_password(file_key, update.effective_user.id, password_hash)

        if success:
            await update.message.reply_text(
                f"🔐 <b>File Locked!</b>\n\n"
                f"🔑 <b>Key:</b> <code>{file_key}</code>\n"
                "Password se hi koi access kar payega.",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text("❌ File nahi mili ya permission nahi hai.")

    async def handle_unlock_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        db_user = await self._guard(update, ctx)
        if not db_user:
            return

        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: <code>/unlock file_key</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0]
        success = await Database.set_file_password(file_key, update.effective_user.id, None)
        if success:
            await update.message.reply_text(f"🔓 File unlocked! Key: <code>{file_key}</code>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ File nahi mili ya permission nahi hai.")

    # ─── Share Link ───────────────────────────────────────────

    async def handle_share_link(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        db_user = await self._guard(update, ctx)
        if not db_user:
            return

        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: <code>/share file_key</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0]
        file_doc = await Database.get_file(file_key)
        if not file_doc or file_doc["owner_id"] != update.effective_user.id:
            await update.message.reply_text("❌ File nahi mili ya permission nahi hai.")
            return

        bot_username = self.cfg.BOT_USERNAME
        if not bot_username:
            await update.message.reply_text("❌ BOT_USERNAME set nahi hai.")
            return

        share_link = f"https://t.me/{bot_username}?start=get_{file_key}"
        emoji = get_file_type_emoji(file_doc.get("file_type", ""))

        text = (
            f"🔗 <b>Share Link Ready!</b>\n\n"
            f"{emoji} <b>{escape_html(file_doc['file_name'])}</b>\n"
            f"💾 {format_size(file_doc.get('file_size', 0))}\n"
            f"{'🔐 Password Protected' if file_doc.get('is_encrypted') else '🔓 Public'}\n\n"
            f"<code>{share_link}</code>"
        )

        buttons = [[
            InlineKeyboardButton("📤 Share", switch_inline_query=share_link),
        ]]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

    # ─── File Info ────────────────────────────────────────────

    async def handle_file_info(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        db_user = await self._guard(update, ctx)
        if not db_user:
            return

        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: <code>/info file_key</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0]
        file_doc = await Database.get_file(file_key)
        if not file_doc:
            await update.message.reply_text("❌ File nahi mili.")
            return

        emoji = get_file_type_emoji(file_doc.get("file_type", ""))
        is_owner = file_doc["owner_id"] == update.effective_user.id
        tags = ", ".join(file_doc.get("tags", [])) or "N/A"

        text = (
            f"{emoji} <b>File Info</b>\n\n"
            f"📄 <b>Name:</b> {escape_html(file_doc['file_name'])}\n"
            f"🔑 <b>Key:</b> <code>{file_key}</code>\n"
            f"💾 <b>Size:</b> {format_size(file_doc.get('file_size', 0))}\n"
            f"📂 <b>Type:</b> {file_doc.get('file_type', 'unknown')}\n"
            f"⬇️ <b>Downloads:</b> {file_doc.get('download_count', 0)}\n"
            f"🔐 <b>Locked:</b> {'Yes' if file_doc.get('is_encrypted') else 'No'}\n"
            f"🌐 <b>Public:</b> {'Yes' if file_doc.get('is_public') else 'No'}\n"
            f"🏷️ <b>Tags:</b> {tags}\n"
            f"📅 <b>Uploaded:</b> {file_doc['uploaded_at'].strftime('%d %b %Y %H:%M')}"
        )

        buttons = []
        if is_owner:
            share_link = f"https://t.me/{self.cfg.BOT_USERNAME}?start=get_{file_key}" if self.cfg.BOT_USERNAME else ""
            buttons = [
                [InlineKeyboardButton("🔗 Share", callback_data=f"file_share_{file_key}")],
                [
                    InlineKeyboardButton("🔐 Lock", callback_data=f"file_lock_{file_key}"),
                    InlineKeyboardButton("❌ Delete", callback_data=f"file_delete_{file_key}"),
                ]
            ]

        await update.effective_message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(buttons) if buttons else None, parse_mode=ParseMode.HTML
        )

    # ─── Search ───────────────────────────────────────────────

    async def handle_search(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        db_user = await self._guard(update, ctx)
        if not db_user:
            return

        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: <code>/search query</code>\n\nFile name ya #tag se search karo.", parse_mode=ParseMode.HTML)
            return

        query = " ".join(args)
        user = update.effective_user
        results = await Database.search_files(user.id, query)

        if not results:
            await update.message.reply_text(f"🔍 <b>No results for:</b> <code>{escape_html(query)}</code>", parse_mode=ParseMode.HTML)
            return

        lines = [f"🔍 <b>Search Results for '{escape_html(query)}':</b>\n"]
        for f in results[:10]:
            emoji = get_file_type_emoji(f.get("file_type", ""))
            locked = "🔐" if f.get("is_encrypted") else ""
            lines.append(
                f"{emoji}{locked} <code>{f['file_key']}</code> — {escape_html(f['file_name'][:35])} ({format_size(f.get('file_size',0))})"
            )

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    # ─── Inline Callbacks ─────────────────────────────────────

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        await q.answer()
        data = q.data
        user = q.from_user

        if data.startswith("file_share_"):
            file_key = data[len("file_share_"):]
            if not self.cfg.BOT_USERNAME:
                await q.message.reply_text("❌ BOT_USERNAME set nahi hai.")
                return
            link = f"https://t.me/{self.cfg.BOT_USERNAME}?start=get_{file_key}"
            await q.message.reply_text(f"🔗 Share Link:\n<code>{link}</code>", parse_mode=ParseMode.HTML)

        elif data.startswith("file_delete_"):
            file_key = data[len("file_delete_"):]
            confirm_btn = [[
                InlineKeyboardButton("✅ Haan Delete Karo", callback_data=f"file_confirmdelete_{file_key}"),
                InlineKeyboardButton("❌ Cancel", callback_data="file_cancel"),
            ]]
            await q.message.reply_text(
                f"⚠️ Sure ho? <code>{file_key}</code> permanently delete ho jayega.",
                reply_markup=InlineKeyboardMarkup(confirm_btn), parse_mode=ParseMode.HTML
            )

        elif data.startswith("file_confirmdelete_"):
            file_key = data[len("file_confirmdelete_"):]
            success = await Database.delete_file(file_key, user.id)
            if success:
                await q.message.edit_text(f"✅ File <code>{file_key}</code> delete ho gayi.", parse_mode=ParseMode.HTML)
            else:
                await q.message.reply_text("❌ Delete failed.")

        elif data.startswith("file_lock_"):
            file_key = data[len("file_lock_"):]
            ctx.user_data["locking_file_key"] = file_key
            await q.message.reply_text(
                f"🔐 File <code>{file_key}</code> ke liye password bhejo:",
                parse_mode=ParseMode.HTML
            )

        elif data.startswith("file_info_"):
            file_key = data[len("file_info_"):]
            ctx.args = [file_key]
            update._effective_message = q.message
            await self.handle_file_info(update, ctx)

        elif data.startswith("file_myfiles_"):
            page = int(data.split("_")[-1])
            ctx.args = [str(page)]
            update._effective_message = q.message
            await self.handle_my_files(update, ctx)

        elif data == "file_cancel":
            await q.message.edit_text("❌ Cancelled.")

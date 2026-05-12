"""
╔═════════════════════════════════════════════════════════════════════════════════════╗
║                        ULTRA VIP TITAN FILE HANDLER ENGINE                          ║
║    God Mode | Multi-File Sync | Real Storage Engine | Advanced Cryptography Lock    ║
╚═════════════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import logging
import math
import asyncio
from typing import Optional, Dict, List, Tuple, Any

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaAudio,
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest, TimedOut, Forbidden

from config import Config
from database.mongodb import Database
from middlewares.force_join import ForceJoinMiddleware
from middlewares.rate_limiter import RateLimiter
from utils.encryption import Encryptor
from utils.helpers import format_size, escape_html, get_file_type_emoji

# ─── System Logger Configuration ─────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ─── Global Singletons for High Performance ──────────────────────────────────
_rate_limiter: Optional[RateLimiter] = None
_encryptor: Optional[Encryptor] = None

# ─── Memory Cache for Batch Uploads (Media Groups) ───────────────────────────
# Ye dictionary track karegi ki ek saath aayi hui files kab khatam hongi
_media_group_cache: Dict[str, Dict[str, Any]] = {}


def get_rate_limiter(cfg: Config) -> RateLimiter:
    """Singleton pattern for rate limiter to prevent memory leaks."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(cfg)
    return _rate_limiter


def get_encryptor(cfg: Config) -> Encryptor:
    """Singleton pattern for Encryptor to reuse hashing objects."""
    global _encryptor
    if _encryptor is None:
        _encryptor = Encryptor(cfg.ENCRYPTION_KEY)
    return _encryptor


class FileSecurityGuard:
    """
    Ek alag class jo strictly security aur permissions manage karti hai.
    Ye check karegi ki koi random user kisi aur ki file delete/rename na kar sake.
    """
    
    @staticmethod
    async def verify_owner(file_doc: dict, user_id: int) -> bool:
        """Returns True if the user is the original uploader."""
        if not file_doc:
            return False
        return str(file_doc.get("owner_id")) == str(user_id)

    @staticmethod
    async def is_locked(file_doc: dict) -> bool:
        """Returns True if the file has an active password lock."""
        if not file_doc:
            return False
        return bool(file_doc.get("is_encrypted") and file_doc.get("password_hash"))


class FileHandler:
    """
    The Titan Controller.
    Manages Uploads, Multi-Forwards, Streaming, Storage calculation, Locks and Security.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.force_join = ForceJoinMiddleware(cfg)
        self.enc = get_encryptor(cfg)
        self.rl = get_rate_limiter(cfg)
        logger.info("⚡ Titan FileHandler Engine Initialized Successfully.")

    # ═════════════════════════════════════════════════════════════════════════════
    # 🛡️ SYSTEM GUARDS & PRE-CHECKS
    # ═════════════════════════════════════════════════════════════════════════════

    async def _system_guard(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> Optional[dict]:
        """
        Master Security Check.
        Checks for Maintenance, Bans, Registration, and Force Join before ANY action.
        """
        user = update.effective_user
        if not user:
            return None

        # 1. Maintenance Override
        if self.cfg.MAINTENANCE_MODE and not self.cfg.is_admin(user.id):
            await update.effective_message.reply_text(
                "⚠️ <b>System Upgrade in Progress</b>\n\n"
                "Engine abhi maintenance mode mein hai. Thodi der mein wapis aana.",
                parse_mode=ParseMode.HTML
            )
            return None

        # 2. Database Sync
        db_user = await Database.get_user(user.id)
        if not db_user:
            db_user = await Database.add_user(user.id, user.username or "", user.first_name or "")
            logger.info(f"🆕 New user registered via Guard: {user.id}")

        # 3. Global Ban Check
        if db_user.get("is_banned"):
            logger.warning(f"🚫 Blocked request from banned user: {user.id}")
            await update.effective_message.reply_text(
                "🚫 <b>Access Denied</b>\nTumhare account ko network se ban kar diya gaya hai.",
                parse_mode=ParseMode.HTML
            )
            return None

        # 4. Mandatory Channel Join Check
        all_joined, not_joined = await self.force_join.check_membership(ctx.bot, user.id)
        if not all_joined:
            await self.force_join.send_join_request(ctx.bot, update.effective_chat.id, not_joined)
            return None

        return db_user

    async def _check_storage_capacity(self, user_id: int, incoming_size: int, db_user: dict) -> Tuple[bool, str]:
        """
        Real Storage Engine Check.
        Calculates if the incoming file will breach the user's maximum quota.
        """
        if self.cfg.is_admin(user_id):
            return True, "Admin Bypass"

        current_usage = db_user.get("storage_used_bytes", 0)
        max_storage = getattr(self.cfg, "MAX_STORAGE_BYTES", 5 * 1024 * 1024 * 1024) # Default 5GB
        
        if (current_usage + incoming_size) > max_storage:
            error_msg = (
                "📦 <b>Storage Limit Exceeded!</b>\n\n"
                f"Your Plan Limit: {format_size(max_storage)}\n"
                f"Current Usage: {format_size(current_usage)}\n"
                f"Incoming File: {format_size(incoming_size)}\n\n"
                "<i>Please delete old files using /myfiles to free up space.</i>"
            )
            return False, error_msg

        return True, "Space Available"

    # ═════════════════════════════════════════════════════════════════════════════
    # 📤 UPLOAD ENGINE (WITH MULTI-FILE / BATCH SUPPORT)
    # ═════════════════════════════════════════════════════════════════════════════

    async def handle_upload(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Main entry point for ANY incoming media/file.
        Automatically detects if it's a single file or a batch (media_group).
        """
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user = update.effective_user
        msg: Message = update.effective_message

        # ─── 1. EXTRACT FILE DATA ───
        file_info = self._extract_file_data(msg)
        if not file_info:
            return # Ignore normal text messages
            
        tg_file_id, file_name, file_size, file_type = file_info

        # ─── 2. RATE LIMITING ───
        if not self.rl.check(user.id, "upload"):
            wait_time = self.rl.get_wait_time(user.id, "upload")
            await msg.reply_text(
                f"⏳ <b>Network Congestion!</b>\nThoda rukko, {wait_time}s baad dubara try karna.",
                parse_mode=ParseMode.HTML
            )
            return

        # ─── 3. FILE SIZE LIMIT CHECK ───
        max_bytes = self.cfg.MAX_FILE_SIZE_MB * 1024 * 1024
        if file_size and file_size > max_bytes:
            await msg.reply_text(
                f"❌ <b>File Too Large!</b>\n\n"
                f"System Limit: {self.cfg.MAX_FILE_SIZE_MB} MB\n"
                f"Your File: {format_size(file_size)}\n\n"
                "<i>Telegram bot limits se badi file direct upload nahi ho sakti.</i>",
                parse_mode=ParseMode.HTML
            )
            return

        # ─── 4. REAL STORAGE QUOTA CHECK ───
        has_space, space_msg = await self._check_storage_capacity(user.id, file_size or 0, db_user)
        if not has_space:
            await msg.reply_text(space_msg, parse_mode=ParseMode.HTML)
            return

        # ─── 5. MEDIA GROUP ROUTING (BATCH UPLOAD) ───
        if msg.media_group_id:
            await self._process_batch_upload(update, ctx, msg, tg_file_id, file_name, file_size, file_type)
            return

        # ─── 6. SINGLE FILE PROCESSING ───
        await self._process_single_upload(update, ctx, msg, tg_file_id, file_name, file_size, file_type)

    async def _process_single_upload(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, msg: Message, tg_file_id: str, file_name: str, file_size: int, file_type: str) -> None:
        """Processes a standalone file upload."""
        user = update.effective_user
        
        # Show processing action
        await ctx.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        processing_msg = await msg.reply_text("⚡ <b>Encrypting and Uploading to Secure Vault...</b>", parse_mode=ParseMode.HTML)

        try:
            # Step 1: Forward to Secure Database Channel
            stored_msg = await ctx.bot.forward_message(
                chat_id=self.cfg.STORAGE_CHANNEL_ID,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id
            )
        except TelegramError as e:
            logger.critical(f"STORAGE FORWARD FAILED for User {user.id}: {e}")
            await processing_msg.edit_text("❌ <b>Fatal Error:</b> Storage backend offline. Contact Admin.", parse_mode=ParseMode.HTML)
            return

        # Step 2: Generate Cryptographic Key
        file_key = self.enc.generate_file_key()

        # Step 3: Extract Tags/Captions
        caption = msg.caption or ""
        tags = [word.lstrip("#").lower() for word in caption.split() if word.startswith("#")]

        # Step 4: Save to MongoDB
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

        # Step 5: Update Real Storage Metrics in User Profile
        await Database.update_user_storage(user.id, file_size or 0, increment=True)

        # Step 6: Generate UI Response
        await self._render_upload_success(processing_msg, file_key, file_name, file_size, file_type)

    async def _process_batch_upload(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, msg: Message, tg_file_id: str, file_name: str, file_size: int, file_type: str) -> None:
        """
        Handles Media Groups (Multiple files sent at once).
        Collects them in memory for a brief window, forwards them safely, and generates a combined UI.
        """
        group_id = msg.media_group_id
        user = update.effective_user

        if group_id not in _media_group_cache:
            _media_group_cache[group_id] = {
                "user_id": user.id,
                "chat_id": msg.chat_id,
                "files": [],
                "processing_msg": None,
                "total_size": 0
            }
            # Create a placeholder message for the batch
            _media_group_cache[group_id]["processing_msg"] = await msg.reply_text(
                "⏳ <b>Batch Upload Detected!</b>\nCollecting multiple files...", 
                parse_mode=ParseMode.HTML
            )
            
            # Start a background task to finalize the batch after a delay
            ctx.application.create_task(self._finalize_batch_upload(ctx, group_id))

        # Add current file to the batch cache
        _media_group_cache[group_id]["files"].append({
            "msg_id": msg.message_id,
            "file_id": tg_file_id,
            "file_name": file_name,
            "file_size": file_size,
            "file_type": file_type,
            "caption": msg.caption or ""
        })
        _media_group_cache[group_id]["total_size"] += (file_size or 0)

    async def _finalize_batch_upload(self, ctx: ContextTypes.DEFAULT_TYPE, group_id: str) -> None:
        """Waits for Telegram to finish sending media group parts, then processes all at once."""
        await asyncio.sleep(3.0) # Wait 3 seconds to catch all parts of the media group

        batch_data = _media_group_cache.pop(group_id, None)
        if not batch_data:
            return

        user_id = batch_data["user_id"]
        chat_id = batch_data["chat_id"]
        files = batch_data["files"]
        proc_msg: Message = batch_data["processing_msg"]
        total_size = batch_data["total_size"]

        await proc_msg.edit_text(
            f"⚡ <b>Processing Batch:</b> {len(files)} files received.\nForwarding to Secure Vault...",
            parse_mode=ParseMode.HTML
        )

        success_keys = []
        
        # Process each file iteratively
        for f in files:
            try:
                # Forward to storage
                stored_msg = await ctx.bot.forward_message(
                    chat_id=self.cfg.STORAGE_CHANNEL_ID,
                    from_chat_id=chat_id,
                    message_id=f["msg_id"]
                )
                
                # Database insertion
                file_key = self.enc.generate_file_key()
                tags = [word.lstrip("#").lower() for word in f["caption"].split() if word.startswith("#")]
                
                await Database.save_file(
                    file_key=file_key,
                    owner_id=user_id,
                    file_id=f["file_id"],
                    file_name=f["file_name"],
                    file_size=f["file_size"] or 0,
                    file_type=f["file_type"],
                    message_id=stored_msg.message_id,
                    tags=tags,
                    caption=f["caption"],
                )
                success_keys.append(file_key)
                
            except Exception as e:
                logger.error(f"Batch item {f['file_name']} failed: {e}")

        # Update global storage
        if success_keys:
            await Database.update_user_storage(user_id, total_size, increment=True)

        # Render Batch Success UI
        batch_summary = (
            f"✅ <b>Batch Upload Successful!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📁 <b>Total Files:</b> {len(success_keys)}\n"
            f"💾 <b>Total Size:</b> {format_size(total_size)}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"<i>You can view all files in your /myfiles vault.</i>"
        )
        
        # Give a link to their files
        btn = [[InlineKeyboardButton("📁 Open My Vault", callback_data="start_myfiles")]]
        await proc_msg.edit_text(batch_summary, reply_markup=InlineKeyboardMarkup(btn), parse_mode=ParseMode.HTML)

    def _extract_file_data(self, msg: Message) -> Optional[Tuple[str, str, int, str]]:
        """Deep extraction of Telegram File MetaData."""
        if msg.document:
            f = msg.document
            return f.file_id, f.file_name or f"document_{f.file_id[:6]}", f.file_size, "document"
        elif msg.video:
            f = msg.video
            name = f.file_name or f"video_{f.duration}s_{f.file_id[:6]}.mp4"
            return f.file_id, name, f.file_size, "video"
        elif msg.audio:
            f = msg.audio
            name = f.file_name or f"{f.performer or 'Unknown'} - {f.title or 'Audio'}.mp3"
            return f.file_id, name, f.file_size, "audio"
        elif msg.photo:
            f = msg.photo[-1] # Highest Quality
            return f.file_id, f"photo_HD_{f.file_id[:8]}.jpg", f.file_size, "photo"
        elif msg.sticker:
            f = msg.sticker
            return f.file_id, f"sticker_{f.file_id[:6]}", f.file_size, "sticker"
        elif msg.voice:
            f = msg.voice
            return f.file_id, f"voice_note_{f.file_id[:6]}.ogg", f.file_size, "voice"
        elif msg.video_note:
            f = msg.video_note
            return f.file_id, f"video_message_{f.file_id[:6]}.mp4", f.file_size, "video_note"
        elif msg.animation:
            f = msg.animation
            return f.file_id, f.file_name or f"gif_{f.file_id[:6]}.mp4", f.file_size, "animation"
        return None

    async def _render_upload_success(self, processing_msg: Message, file_key: str, file_name: str, file_size: int, file_type: str) -> None:
        """Builds the VIP UI after a successful single upload."""
        bot_username = self.cfg.BOT_USERNAME
        share_link = f"https://t.me/{bot_username}?start=get_{file_key}" if bot_username else None
        emoji = get_file_type_emoji(file_type)

        buttons = [
            [InlineKeyboardButton("🔗 Share Direct Link", callback_data=f"file_share_{file_key}")],
            [
                InlineKeyboardButton("🔐 Lock Access", callback_data=f"file_lock_{file_key}"),
                InlineKeyboardButton("✏️ Rename", callback_data=f"file_renamemenu_{file_key}"),
            ],
            [
                InlineKeyboardButton("📋 View File Specs", callback_data=f"file_info_{file_key}"),
                InlineKeyboardButton("❌ Destroy", callback_data=f"file_delete_{file_key}"),
            ]
        ]
        markup = InlineKeyboardMarkup(buttons)

        result_text = (
            f"✅ <b>Upload Secured & Encrypted</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} <b>Name:</b> {escape_html(file_name)}\n"
            f"💾 <b>Size:</b> {format_size(file_size or 0)}\n"
            f"🔑 <b>Vault Key:</b> <code>{file_key}</code>\n"
        )
        if share_link:
            result_text += f"\n🔗 <b>Share URL:</b>\n<code>{share_link}</code>"

        await processing_msg.edit_text(result_text, reply_markup=markup, parse_mode=ParseMode.HTML)


    # ═════════════════════════════════════════════════════════════════════════════
    # 📥 FETCH & DELIVERY ENGINE (DEEP LINKS & COMMANDS)
    # ═════════════════════════════════════════════════════════════════════════════

    async def handle_get_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Entry point for /get command."""
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        args = ctx.args
        if not args:
            await update.message.reply_text(
                "⚠️ <b>Invalid Syntax</b>\nUsage: <code>/get FILE_KEY</code>\n\n"
                "<i>File key aapko upload karne ke baad milti hai.</i>",
                parse_mode=ParseMode.HTML
            )
            return

        file_key = args[0].strip()
        await self._deliver_file(update, ctx, file_key)

    async def _deliver_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, file_key: str) -> None:
        """
        The core engine that pulls files from DB, checks locks, and sends to user.
        """
        user = update.effective_user
        msg = update.effective_message

        # Fetch from DB
        file_doc = await Database.get_file(file_key)
        if not file_doc:
            await msg.reply_text("❌ <b>File Not Found!</b>\nYe file ya toh delete ho chuki hai ya key galat hai.", parse_mode=ParseMode.HTML)
            return

        # Anti-Spam Rate Limit
        if not self.rl.check(user.id, "download"):
            wait = self.rl.get_wait_time(user.id, "download")
            await msg.reply_text(f"⏳ <b>Rate Limit Active:</b> Please wait {wait} seconds.", parse_mode=ParseMode.HTML)
            return

        # ─── 🔐 SECURITY: PASSWORD LOCK CHECK ───
        if await FileSecurityGuard.is_locked(file_doc):
            # Agar file lock hai, toh user se password mangna padega
            ctx.user_data["unlocking_file_key"] = file_key
            ctx.user_data["awaiting_action"] = "unlock_password"
            
            await msg.reply_text(
                f"🔐 <b>RESTRICTED ACCESS</b>\n\n"
                f"File: <code>{escape_html(file_doc['file_name'])}</code>\n"
                f"Ye file owner ne password se lock ki hui hai.\n\n"
                f"👇 <b>Kripya neeche chat mein iska password type karke bhejein:</b>",
                parse_mode=ParseMode.HTML
            )
            return

        # File un-locked hai, direct bhejo
        await self._send_file_from_storage(msg, ctx, file_doc)

    async def _send_file_from_storage(self, msg: Message, ctx: ContextTypes.DEFAULT_TYPE, file_doc: dict) -> None:
        """Physical transfer of file from Storage Channel to the User via Bot."""
        # Show realistic action
        await ctx.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        
        try:
            # Copy file (This prevents the original uploader from being exposed)
            sent_msg = await ctx.bot.copy_message(
                chat_id=msg.chat_id,
                from_chat_id=self.cfg.STORAGE_CHANNEL_ID,
                message_id=file_doc["message_id"],
                caption=file_doc.get("caption") or f"📄 <b>{escape_html(file_doc['file_name'])}</b>\n🤖 @{self.cfg.BOT_USERNAME}",
                parse_mode=ParseMode.HTML
            )
            
            # Update analytics
            await Database.increment_download(file_doc["file_key"])

            # Send metadata below file
            info_btn = [[InlineKeyboardButton("📋 Specs", callback_data=f"file_info_{file_doc['file_key']}")]]
            await sent_msg.reply_text(
                f"✅ <b>File Delivery Complete!</b>\n"
                f"💾 {format_size(file_doc.get('file_size',0))}",
                reply_markup=InlineKeyboardMarkup(info_btn),
                parse_mode=ParseMode.HTML
            )
        except TelegramError as e:
            logger.error(f"Critical error during file delivery: {e}")
            await msg.reply_text("❌ <b>Transmission Error:</b> Database server connect nahi ho pa raha.", parse_mode=ParseMode.HTML)


    # ═════════════════════════════════════════════════════════════════════════════
    # 🗄️ MY VAULT (FILE INVENTORY)
    # ═════════════════════════════════════════════════════════════════════════════

    async def handle_my_files(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Generates a paginated interactive dashboard of user's files."""
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user = update.effective_user
        args = ctx.args
        page = 1
        if args and args[0].isdigit():
            page = max(1, int(args[0]))

        per_page = 7 # Elite layout spacing
        
        # Parallel database fetch for speed
        files, total = await asyncio.gather(
            Database.get_user_files(user.id, page=page, per_page=per_page),
            Database.count_user_files(user.id)
        )
        
        total_pages = max(1, math.ceil(total / per_page))

        if not files:
            await update.effective_message.reply_text(
                "📭 <b>Your Vault is Empty!</b>\n\n"
                "Abhi tak koi file upload nahi ki hai. Chat mein koi file bhej kar shuruwat karein.",
                parse_mode=ParseMode.HTML
            )
            return

        lines = [
            f"🗄️ <b>YOUR SECURE VAULT</b>",
            f"📊 Page <b>{page}/{total_pages}</b> | Total Files: <b>{total}</b>\n"
        ]
        
        for i, f in enumerate(files, 1):
            emoji = get_file_type_emoji(f.get("file_type", ""))
            locked = "🔐" if await FileSecurityGuard.is_locked(f) else "🔓"
            name = escape_html(f["file_name"][:35]) + ("..." if len(f["file_name"]) > 35 else "")
            size = format_size(f.get("file_size", 0))
            dl = f.get("download_count", 0)
            
            lines.append(
                f"<b>{i}.</b> {emoji} {name}\n"
                f"   └ 🔑 <code>{f['file_key']}</code> | 💾 {size} | ⬇️ {dl} | {locked}\n"
            )

        text = "\n".join(lines)

        # Smart Pagination UI
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data=f"file_myfiles_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"file_myfiles_{page+1}"))

        markup = InlineKeyboardMarkup([nav_buttons] if nav_buttons else [])
        
        # Typing feel
        await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)


    # ═════════════════════════════════════════════════════════════════════════════
    # ❌ DELETION ENGINE (WITH REAL STORAGE MINUS LOGIC)
    # ═════════════════════════════════════════════════════════════════════════════

    async def handle_delete_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Deletes file from DB AND decrements user's used storage."""
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user_id = update.effective_user.id
        args = ctx.args
        if not args:
            await update.effective_message.reply_text("⚠️ Syntax: <code>/delete FILE_KEY</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0].strip()
        
        # Validate Ownership & Calculate Size before deleting
        file_doc = await Database.get_file(file_key)
        if not file_doc:
            await update.effective_message.reply_text("❌ File not found.", parse_mode=ParseMode.HTML)
            return

        if not await FileSecurityGuard.verify_owner(file_doc, user_id) and not self.cfg.is_admin(user_id):
            await update.effective_message.reply_text("🛑 <b>Security Alert:</b> You don't own this file!", parse_mode=ParseMode.HTML)
            return

        file_size = file_doc.get("file_size", 0)

        # Perform Deletion
        success = await Database.delete_file(file_key, user_id)
        if success:
            # 📉 REAL STORAGE MINUS ENGINE
            await Database.update_user_storage(user_id, file_size, increment=False)
            
            await update.effective_message.reply_text(
                f"🗑️ <b>Asset Destroyed!</b>\n\n"
                f"File <code>{file_key}</code> has been permanently removed.\n"
                f"📉 Storage freed: <b>{format_size(file_size)}</b>", 
                parse_mode=ParseMode.HTML
            )
        else:
            await update.effective_message.reply_text("❌ Deletion process failed at database level.")


    # ═════════════════════════════════════════════════════════════════════════════
    # 🔐 CRYPTOGRAPHY & PASSWORD ENGINE (Lock/Unlock)
    # ═════════════════════════════════════════════════════════════════════════════

    async def handle_lock_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Triggers the lock UI. Requires password input via text next."""
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user_id = update.effective_user.id
        args = ctx.args
        
        if not args:
            await update.effective_message.reply_text("⚠️ Syntax: <code>/lock FILE_KEY</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0].strip()
        
        # Ownership guard
        file_doc = await Database.get_file(file_key)
        if not file_doc or not await FileSecurityGuard.verify_owner(file_doc, user_id):
            await update.effective_message.reply_text("🛑 <b>Denied:</b> You can only lock your own files.", parse_mode=ParseMode.HTML)
            return

        # Setup Conversation State
        ctx.user_data["action_file_key"] = file_key
        ctx.user_data["awaiting_action"] = "set_lock_password"
        
        await update.effective_message.reply_text(
            f"🔐 <b>Locking Protocol Initiated</b>\n\n"
            f"File: <code>{file_key}</code>\n"
            f"Please type a strong password in the chat below to secure this file.\n"
            f"(Minimum 4 characters required)",
            parse_mode=ParseMode.HTML
        )

    async def handle_unlock_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Removes the cryptographic hash from the database."""
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user_id = update.effective_user.id
        args = ctx.args
        if not args:
            await update.effective_message.reply_text("⚠️ Syntax: <code>/unlock FILE_KEY</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0].strip()
        
        # Strict Ownership Check
        file_doc = await Database.get_file(file_key)
        if not file_doc or not await FileSecurityGuard.verify_owner(file_doc, user_id):
            await update.effective_message.reply_text("🛑 <b>Denied:</b> You can't unlock someone else's file.", parse_mode=ParseMode.HTML)
            return

        # Perform unlock
        success = await Database.set_file_password(file_key, user_id, None)
        if success:
            await update.effective_message.reply_text(
                f"🔓 <b>Vault Opened</b>\nFile <code>{file_key}</code> is now publicly accessible.", 
                parse_mode=ParseMode.HTML
            )
        else:
            await update.effective_message.reply_text("❌ System Error during unlock process.")

    # ═════════════════════════════════════════════════════════════════════════════
    # ⌨️ DYNAMIC TEXT INPUT ROUTER (For Passwords & Renaming)
    # ═════════════════════════════════════════════════════════════════════════════
    # NOTE: Your main `bot.py` needs a `MessageHandler(filters.TEXT & ~filters.COMMAND, file_h.handle_text_input)`

    async def handle_text_input(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        The brain that catches passwords and renames when the bot asks a question.
        Replaces ugly command-based renaming/locking.
        """
        msg = update.effective_message
        if not msg.text:
            return

        action = ctx.user_data.get("awaiting_action")
        
        # 1. Action: Setting a Lock Password
        if action == "set_lock_password":
            file_key = ctx.user_data.get("action_file_key")
            password = msg.text.strip()
            
            if len(password) < 4:
                await msg.reply_text("❌ Too short! Password must be at least 4 characters. Try again:")
                return
                
            enc = get_encryptor(self.cfg)
            hashed_pw = enc.hash_password(password)
            
            if await Database.set_file_password(file_key, update.effective_user.id, hashed_pw):
                await msg.reply_text(
                    f"✅ <b>Lock Active!</b>\nFile <code>{file_key}</code> is now heavily encrypted.\n"
                    f"⚠️ <i>Please memorize your password, it cannot be recovered.</i>",
                    parse_mode=ParseMode.HTML
                )
            # Clear state
            ctx.user_data.pop("awaiting_action", None)
            ctx.user_data.pop("action_file_key", None)
            
        # 2. Action: Trying to Unlock/Fetch a File
        elif action == "unlock_password":
            file_key = ctx.user_data.get("unlocking_file_key")
            input_pw = msg.text.strip()
            
            file_doc = await Database.get_file(file_key)
            if not file_doc:
                ctx.user_data.pop("awaiting_action", None)
                return
                
            enc = get_encryptor(self.cfg)
            saved_hash = file_doc.get("password_hash")
            
            if enc.verify_password(input_pw, saved_hash):
                # Password Correct! Deliver file.
                await msg.reply_text("✅ <b>Password Accepted.</b> Decrypting vault...", parse_mode=ParseMode.HTML)
                ctx.user_data.pop("awaiting_action", None)
                ctx.user_data.pop("unlocking_file_key", None)
                await self._send_file_from_storage(msg, ctx, file_doc)
            else:
                await msg.reply_text("❌ <b>INCORRECT PASSWORD</b>\nIntrusion attempt logged. Try again:")
                
        # 3. Action: Renaming a File
        elif action == "rename_file":
            file_key = ctx.user_data.get("action_file_key")
            new_name = msg.text.strip()
            
            if await Database.rename_file(file_key, update.effective_user.id, new_name):
                await msg.reply_text(f"✅ <b>Name Updated:</b>\n<code>{escape_html(new_name)}</code>", parse_mode=ParseMode.HTML)
            else:
                await msg.reply_text("❌ Failed to rename.")
                
            ctx.user_data.pop("awaiting_action", None)
            ctx.user_data.pop("action_file_key", None)


    # ═════════════════════════════════════════════════════════════════════════════
    # 📋 FILE SPECS & LINK GENERATION
    # ═════════════════════════════════════════════════════════════════════════════

    async def handle_file_info(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Massive detailed panel for file specifications."""
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        args = ctx.args
        if not args:
            await update.effective_message.reply_text("⚠️ Syntax: <code>/info FILE_KEY</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0].strip()
        file_doc = await Database.get_file(file_key)
        if not file_doc:
            await update.effective_message.reply_text("❌ File not found in database.", parse_mode=ParseMode.HTML)
            return

        emoji = get_file_type_emoji(file_doc.get("file_type", ""))
        is_owner = await FileSecurityGuard.verify_owner(file_doc, update.effective_user.id)
        tags = ", ".join(file_doc.get("tags", [])) or "None"
        locked = "🔐 Yes (Encrypted)" if await FileSecurityGuard.is_locked(file_doc) else "🔓 No (Public)"

        text = (
            f"📑 <b>ASSET SPECIFICATIONS</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} <b>Filename:</b> {escape_html(file_doc['file_name'])}\n"
            f"🔑 <b>Hash Key:</b> <code>{file_key}</code>\n"
            f"💾 <b>Footprint:</b> {format_size(file_doc.get('file_size', 0))}\n"
            f"📂 <b>Format:</b> {file_doc.get('file_type', 'unknown').upper()}\n"
            f"⬇️ <b>Network Trafffic:</b> {file_doc.get('download_count', 0)} downloads\n"
            f"🔒 <b>Security Status:</b> {locked}\n"
            f"🏷️ <b>Metadata Tags:</b> {tags}\n"
            f"📅 <b>Archived On:</b> {file_doc['uploaded_at'].strftime('%d %b %Y %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

        buttons = []
        if is_owner:
            buttons = [
                [InlineKeyboardButton("🔗 Generate Link", callback_data=f"file_share_{file_key}")],
                [
                    InlineKeyboardButton("🔐 Lock", callback_data=f"file_lock_{file_key}"),
                    InlineKeyboardButton("✏️ Rename", callback_data=f"file_renamemenu_{file_key}"),
                ],
                [InlineKeyboardButton("❌ Destroy Asset", callback_data=f"file_delete_{file_key}")]
            ]

        await update.effective_message.reply_text(
            text, 
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None, 
            parse_mode=ParseMode.HTML
        )


    # ═════════════════════════════════════════════════════════════════════════════
    # ⚡ ZERO-LAG CALLBACK ROUTER (THE EVENT ENGINE)
    # ═════════════════════════════════════════════════════════════════════════════

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Ultimate Callback Router.
        Catches all button presses related to files and routes them seamlessly.
        """
        q = update.callback_query
        
        # ZERO LAG IMPLEMENTATION
        try:
            await q.answer()
        except Exception as e:
            logger.warning(f"Failed to answer callback, might be expired: {e}")
            return

        data = q.data
        user = q.from_user

        try:
            # ─── SHARE LINK LOGIC ───
            if data.startswith("file_share_"):
                file_key = data[len("file_share_"):]
                bot_user = self.cfg.BOT_USERNAME
                link = f"https://t.me/{bot_user}?start=get_{file_key}"
                
                await q.message.reply_text(
                    f"🔗 <b>Secure Distribution Link</b>\n\n<code>{link}</code>\n\n"
                    f"<i>Tap to copy. Anyone with this link can fetch the file via the bot.</i>", 
                    parse_mode=ParseMode.HTML
                )

            # ─── DELETE WARNING LOGIC ───
            elif data.startswith("file_delete_"):
                file_key = data[len("file_delete_"):]
                confirm_btn = [
                    [InlineKeyboardButton("⚠️ YES, DESTROY IT", callback_data=f"file_confirmdel_{file_key}")],
                    [InlineKeyboardButton("❌ CANCEL", callback_data="file_cancel_action")],
                ]
                await q.message.reply_text(
                    f"🛑 <b>CRITICAL WARNING</b>\nAre you sure you want to permanently delete <code>{file_key}</code>?\nThis action cannot be reversed and storage will be reclaimed.",
                    reply_markup=InlineKeyboardMarkup(confirm_btn), 
                    parse_mode=ParseMode.HTML
                )

            # ─── CONFIRM DELETE LOGIC ───
            elif data.startswith("file_confirmdel_"):
                file_key = data[len("file_confirmdel_"):]
                
                # Fetch size for storage deduction
                file_doc = await Database.get_file(file_key)
                if not file_doc:
                    await q.message.edit_text("❌ File already gone.")
                    return
                
                f_size = file_doc.get("file_size", 0)
                
                if await Database.delete_file(file_key, user.id):
                    await Database.update_user_storage(user.id, f_size, increment=False)
                    await q.message.edit_text(
                        f"✅ <b>Asset Purged!</b>\n<code>{file_key}</code> deleted.\nStorage recovered: {format_size(f_size)}", 
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await q.message.edit_text("❌ Deletion Failed. Permission denied.")

            # ─── RENAME INITIATION LOGIC ───
            elif data.startswith("file_renamemenu_"):
                file_key = data[len("file_renamemenu_"):]
                ctx.user_data["action_file_key"] = file_key
                ctx.user_data["awaiting_action"] = "rename_file"
                await q.message.reply_text(
                    f"✏️ <b>Rename Mode Activated</b>\n\n"
                    f"Target: <code>{file_key}</code>\n"
                    f"👇 Please type the NEW name for this file below:",
                    parse_mode=ParseMode.HTML
                )

            # ─── LOCK INITIATION LOGIC ───
            elif data.startswith("file_lock_"):
                file_key = data[len("file_lock_"):]
                ctx.user_data["action_file_key"] = file_key
                ctx.user_data["awaiting_action"] = "set_lock_password"
                await q.message.reply_text(
                    f"🔐 <b>Lock Sequence Initiated</b>\n\n"
                    f"Target: <code>{file_key}</code>\n"
                    f"👇 Please type the NEW PASSWORD for this file below:",
                    parse_mode=ParseMode.HTML
                )

            # ─── PAGINATION (MY FILES) ───
            elif data.startswith("file_myfiles_"):
                page = int(data.split("_")[-1])
                ctx.args = [str(page)]
                update._effective_message = q.message
                await self.handle_my_files(update, ctx)

            # ─── INFO PANEL ───
            elif data.startswith("file_info_"):
                file_key = data[len("file_info_"):]
                ctx.args = [file_key]
                update._effective_message = q.message
                await self.handle_file_info(update, ctx)

            # ─── CANCEL ACTION ───
            elif data == "file_cancel_action":
                ctx.user_data.pop("awaiting_action", None)
                await q.message.edit_text("✅ <b>Action Aborted.</b>", parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.error(f"Error executing callback {data}: {e}", exc_info=True)
            await q.message.reply_text("⚠️ UI Framework Timeout. Try sending command directly.", parse_mode=ParseMode.HTML)


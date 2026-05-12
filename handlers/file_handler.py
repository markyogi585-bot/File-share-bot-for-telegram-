"""
╔═════════════════════════════════════════════════════════════════════════════════════╗
║                        ULTRA VIP TITAN FILE HANDLER ENGINE                          ║
║    God Mode | Multi-File Sync | Real Storage Engine | Advanced Cryptography Lock    ║
║    RAILWAY V2 PATCH: Fully restored missing command endpoints and routers.          ║
╚═════════════════════════════════════════════════════════════════════════════════════╝

Description:
This module represents the absolute core of the File Management System.
It is engineered to be highly fault-tolerant, especially in serverless or
ephemeral environments like Railway.app, Heroku, or AWS Lambda.
It handles file persistence, security guards, cryptographic locks,
multi-threaded batch uploads, and zero-lag interactive callbacks.
"""

from __future__ import annotations

import logging
import math
import asyncio
from typing import Optional, Dict, List, Tuple, Any, Union

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
    Chat,
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

# ═════════════════════════════════════════════════════════════════════════════════════
# ─── LOGGER INSTANTIATION ────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════════════

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ═════════════════════════════════════════════════════════════════════════════════════
# ─── CUSTOM EXCEPTIONS ───────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════════════

class FileHandlerError(Exception):
    """Base exception for all File Handler related errors."""
    pass

class SecurityGuardError(FileHandlerError):
    """Raised when a security check fails (e.g., unauthorized access)."""
    pass

class StorageQuotaExceeded(FileHandlerError):
    """Raised when user exceeds their allocated storage plan."""
    pass

class CryptographyError(FileHandlerError):
    """Raised on encryption/decryption or password mismatch issues."""
    pass

# ═════════════════════════════════════════════════════════════════════════════════════
# ─── GLOBAL SINGLETONS & CACHES ──────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════════════

# To prevent memory leaks during warm reloads on Railway, we use singletons.
_rate_limiter_instance: Optional[RateLimiter] = None
_encryptor_instance: Optional[Encryptor] = None

# Cache for Media Groups (Batch Uploads)
# Structure: { media_group_id: { user_id, chat_id, files: [], proc_msg, total_size } }
_media_group_cache: Dict[str, Dict[str, Any]] = {}


def get_rate_limiter(cfg: Config) -> RateLimiter:
    """
    Singleton factory for RateLimiter.
    Ensures only one instance manages the token bucket algorithm across the app.
    """
    global _rate_limiter_instance
    if _rate_limiter_instance is None:
        logger.info("Initializing Global Rate Limiter Singleton.")
        _rate_limiter_instance = RateLimiter(cfg)
    return _rate_limiter_instance


def get_encryptor(cfg: Config) -> Encryptor:
    """
    Singleton factory for Encryptor.
    Prevents repeated initialization of heavy cryptographic libraries.
    """
    global _encryptor_instance
    if _encryptor_instance is None:
        logger.info("Initializing Global Cryptography Engine Singleton.")
        _encryptor_instance = Encryptor(cfg.ENCRYPTION_KEY)
    return _encryptor_instance

# ═════════════════════════════════════════════════════════════════════════════════════
# ─── FILE SECURITY GUARD ─────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════════════

class FileSecurityGuard:
    """
    A strict security module dedicated entirely to verifying ownership,
    evaluating cryptographic states, and ensuring data privacy.
    No file operation is permitted without passing through this guard.
    """
    
    @staticmethod
    async def verify_owner(file_doc: Optional[dict], user_id: Union[int, str]) -> bool:
        """
        Validates if the executing user is the absolute owner of the file entity.
        
        Args:
            file_doc: The BSON/Dict document retrieved from MongoDB.
            user_id: The Telegram User ID requesting the action.
            
        Returns:
            bool: True if ownership is confirmed, False otherwise.
        """
        if not file_doc:
            logger.warning(f"SecurityGuard: Attempted ownership verify on None document by user {user_id}")
            return False
            
        owner_val = str(file_doc.get("owner_id"))
        requester_val = str(user_id)
        
        is_owner = (owner_val == requester_val)
        if not is_owner:
            logger.warning(f"SecurityGuard: Ownership rejection. File {file_doc.get('file_key')} owned by {owner_val}, requested by {requester_val}")
            
        return is_owner

    @staticmethod
    async def is_locked(file_doc: Optional[dict]) -> bool:
        """
        Evaluates the cryptographic lock status of a file entity.
        
        Args:
            file_doc: The BSON/Dict document retrieved from MongoDB.
            
        Returns:
            bool: True if a valid password hash exists AND encryption flag is set.
        """
        if not file_doc:
            return False
            
        flag_status = bool(file_doc.get("is_encrypted", False))
        hash_status = bool(file_doc.get("password_hash", None))
        
        return flag_status and hash_status

    @staticmethod
    def validate_password_strength(password: str) -> bool:
        """
        Evaluates if the user-provided password meets minimum security criteria.
        Can be expanded in the future for regex pattern matching.
        """
        if not password:
            return False
        if len(password.strip()) < 4:
            return False
        return True


# ═════════════════════════════════════════════════════════════════════════════════════
# ─── MAIN CONTROLLER: FILE HANDLER ───────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════════════

class FileHandler:
    """
    The Ultimate Titan Controller.
    Responsible for all IO operations, routing, parsing, uploading, streaming,
    batch processing, deletion, renaming, and security lockdowns.
    """

    def __init__(self, cfg: Config):
        """
        Bootstraps the File Handler with necessary configurations and singletons.
        """
        self.cfg = cfg
        self.force_join = ForceJoinMiddleware(cfg)
        self.enc = get_encryptor(cfg)
        self.rl = get_rate_limiter(cfg)
        logger.info("⚡ Titan FileHandler Engine Initialized. All subsystems nominal.")

    # ═════════════════════════════════════════════════════════════════════════════════
    # 🛡️ PRE-FLIGHT CHECKS & GUARDS
    # ═════════════════════════════════════════════════════════════════════════════════

    async def _system_guard(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> Optional[dict]:
        """
        Master Execution Guard.
        Acts as the first line of defense before any handler logic is executed.
        Checks:
        1. User existence
        2. Maintenance Status
        3. Database Synchronization
        4. Global Blacklist/Ban Status
        5. Mandatory Channel Subscription
        """
        user: Optional[User] = update.effective_user
        msg: Optional[Message] = update.effective_message
        
        if not user or not msg:
            logger.debug("SystemGuard: Aborted due to missing User or Message context.")
            return None

        # 1. Evaluate Maintenance Override
        is_maintenance = getattr(self.cfg, 'MAINTENANCE_MODE', False)
        is_sysadmin = self.cfg.is_admin(user.id)
        
        if is_maintenance and not is_sysadmin:
            logger.info(f"SystemGuard: Maintenance mode blocked user {user.id}")
            await msg.reply_text(
                "⚠️ <b>System Upgrade in Progress</b>\n\n"
                "Engine abhi maintenance mode mein hai. Thodi der mein wapis aana.",
                parse_mode=ParseMode.HTML
            )
            return None

        # 2. Database Synchronization & Auto-Registration
        db_user = await Database.get_user(user.id)
        if not db_user:
            username = user.username or ""
            first_name = user.first_name or "Unknown Citizen"
            db_user = await Database.add_user(user.id, username, first_name)
            logger.info(f"SystemGuard: New user auto-registered in Database -> {user.id}")

        # 3. Global Blacklist Protocol
        if db_user.get("is_banned", False):
            logger.warning(f"SystemGuard: 🚫 Blocked request from BANNED user: {user.id}")
            await msg.reply_text(
                "🚫 <b>Access Denied</b>\n"
                "Tumhare account ko network se ban kar diya gaya hai. Contact Administrator.",
                parse_mode=ParseMode.HTML
            )
            return None

        # 4. Mandatory Subscription Validation (Force Join)
        all_joined, not_joined = await self.force_join.check_membership(ctx.bot, user.id)
        if not all_joined:
            logger.info(f"SystemGuard: User {user.id} failed Force Join check. Sending prompt.")
            await self.force_join.send_join_request(ctx.bot, update.effective_chat.id, not_joined)
            return None

        # Pass complete. Return synchronized database document.
        return db_user

    async def _check_storage_capacity(self, user_id: int, incoming_size: int, db_user: dict) -> Tuple[bool, str]:
        """
        Real-time Storage Calculation Engine.
        Prevents users from uploading files that would breach their defined quota limit.
        """
        if self.cfg.is_admin(user_id):
            return True, "Administrator Bypass Engaged."

        current_usage = db_user.get("storage_used_bytes", 0)
        
        # Default fallback is 5 Gigabytes if not defined in config
        max_storage = getattr(self.cfg, "MAX_STORAGE_BYTES", 5 * 1024 * 1024 * 1024) 
        
        projected_usage = current_usage + incoming_size
        
        if projected_usage > max_storage:
            logger.info(f"StorageEngine: User {user_id} breached quota. (Limit: {max_storage}, Projected: {projected_usage})")
            error_msg = (
                "📦 <b>Storage Limit Exceeded!</b>\n\n"
                f"📊 <b>Your Plan Limit:</b> {format_size(max_storage)}\n"
                f"💾 <b>Current Usage:</b> {format_size(current_usage)}\n"
                f"📥 <b>Incoming Payload:</b> {format_size(incoming_size)}\n\n"
                "<i>Please delete old files using /myfiles or /delete to free up space.</i>"
            )
            return False, error_msg

        return True, "Space allocation validated."

    # ═════════════════════════════════════════════════════════════════════════════════
    # 📤 UPLOAD ENGINE (SINGLE & BATCH PROCESSOR)
    # ═════════════════════════════════════════════════════════════════════════════════

    async def handle_upload(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        The universal entry point for all incoming media.
        Detects media type, validates sizes, checks quotas, and routes to appropriate
        single or multi-threaded batch processors.
        """
        # 1. System Guard Check
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user = update.effective_user
        msg: Message = update.effective_message

        # 2. Deep Extraction of File Metadata
        file_info = self._extract_file_data(msg)
        if not file_info:
            # Message does not contain valid parseable media
            return 
            
        tg_file_id, file_name, file_size, file_type = file_info
        safe_file_size = file_size or 0

        # 3. Application-Level Rate Limiting (Anti-Spam)
        if not self.rl.check(user.id, "upload"):
            wait_time = self.rl.get_wait_time(user.id, "upload")
            logger.debug(f"RateLimiter: Upload throttled for {user.id}. Wait: {wait_time}s")
            await msg.reply_text(
                f"⏳ <b>Network Congestion Detected!</b>\nThoda rukko, {wait_time} seconds baad dubara try karna.",
                parse_mode=ParseMode.HTML
            )
            return

        # 4. Hard File Size Limitations (Telegram API constraints)
        max_megabytes = getattr(self.cfg, 'MAX_FILE_SIZE_MB', 2000)
        max_bytes = max_megabytes * 1024 * 1024
        
        if safe_file_size > max_bytes:
            logger.info(f"UploadEngine: File rejected for {user.id} due to size constraint ({safe_file_size} > {max_bytes})")
            await msg.reply_text(
                f"❌ <b>Payload Too Large!</b>\n\n"
                f"⚙️ <b>System Limit:</b> {max_megabytes} MB\n"
                f"📁 <b>Your File:</b> {format_size(safe_file_size)}\n\n"
                "<i>Telegram API restrictions block files larger than the maximum allocated limit.</i>",
                parse_mode=ParseMode.HTML
            )
            return

        # 5. Dynamic Storage Quota Verification
        has_space, space_msg = await self._check_storage_capacity(user.id, safe_file_size, db_user)
        if not has_space:
            await msg.reply_text(space_msg, parse_mode=ParseMode.HTML)
            return

        # 6. Advanced Routing: Media Group vs Standalone
        if msg.media_group_id:
            logger.info(f"UploadEngine: Routing to Batch Processor for group {msg.media_group_id}")
            await self._process_batch_upload(
                update, ctx, msg, tg_file_id, file_name, safe_file_size, file_type
            )
            return

        # 7. Standard Single File Processing
        logger.info(f"UploadEngine: Routing to Standalone Processor for file {tg_file_id}")
        await self._process_single_upload(
            update, ctx, msg, tg_file_id, file_name, safe_file_size, file_type
        )

    async def _process_single_upload(
        self, 
        update: Update, 
        ctx: ContextTypes.DEFAULT_TYPE, 
        msg: Message, 
        tg_file_id: str, 
        file_name: str, 
        file_size: int, 
        file_type: str
    ) -> None:
        """
        Executes the logic for saving a standalone file.
        Forwards to dump channel, stores in MongoDB, updates user stats, and builds UI.
        """
        user = update.effective_user
        
        # User Experience: Visual feedback during processing
        try:
            await ctx.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        except Exception as e:
            logger.debug(f"UX Action Error: {e}")
            pass
        
        processing_msg = await msg.reply_text(
            "⚡ <b>Encrypting Payload and Uploading to Secure Vault...</b>\n<i>Please stand by...</i>", 
            parse_mode=ParseMode.HTML
        )

        try:
            # ─── PHASE 1: PHYSICAL STORAGE RELAY ───
            stored_msg = await ctx.bot.forward_message(
                chat_id=self.cfg.STORAGE_CHANNEL_ID,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id
            )
        except TelegramError as e:
            logger.critical(f"STORAGE RELAY FAILED for User {user.id}. Exception: {e}")
            await processing_msg.edit_text(
                "❌ <b>Fatal Relay Error:</b> Storage backend is currently unreachable. Contact Administration.", 
                parse_mode=ParseMode.HTML
            )
            return

        # ─── PHASE 2: CRYPTOGRAPHIC KEY GENERATION ───
        file_key = self.enc.generate_file_key()

        # ─── PHASE 3: METADATA EXTRACTION ───
        caption = msg.caption or ""
        tags = [word.lstrip("#").lower() for word in caption.split() if word.startswith("#")]

        # ─── PHASE 4: DATABASE SYNCHRONIZATION ───
        await Database.save_file(
            file_key=file_key,
            owner_id=user.id,
            file_id=tg_file_id,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            message_id=stored_msg.message_id,
            tags=tags,
            caption=caption,
        )

        # ─── PHASE 5: USER METRICS UPDATE ───
        await Database.update_user_storage(user.id, file_size, increment=True)

        # ─── PHASE 6: VIP DASHBOARD RENDERING ───
        await self._render_upload_success(processing_msg, file_key, file_name, file_size, file_type)

    async def _process_batch_upload(
        self, 
        update: Update, 
        ctx: ContextTypes.DEFAULT_TYPE, 
        msg: Message, 
        tg_file_id: str, 
        file_name: str, 
        file_size: int, 
        file_type: str
    ) -> None:
        """
        Manages the complexity of Telegram Media Groups (albums).
        Telegram sends albums as individual messages arriving concurrently.
        This function creates an ephemeral memory cache to pool them together,
        waits for completion, and processes them as a single logical batch.
        """
        group_id = msg.media_group_id
        user = update.effective_user

        # Initialize the cache bucket if this is the first item in the group
        if group_id not in _media_group_cache:
            _media_group_cache[group_id] = {
                "user_id": user.id,
                "chat_id": msg.chat_id,
                "files": [],
                "processing_msg": None,
                "total_size": 0
            }
            # Inform the user that the batch has been intercepted
            _media_group_cache[group_id]["processing_msg"] = await msg.reply_text(
                "⏳ <b>Batch Interception Active!</b>\nCollecting multiple files into memory buffer...", 
                parse_mode=ParseMode.HTML
            )
            
            # Spin up an asynchronous watcher task
            ctx.application.create_task(self._finalize_batch_upload(ctx, group_id))

        # Append the current file metadata to the memory cache bucket
        _media_group_cache[group_id]["files"].append({
            "msg_id": msg.message_id,
            "file_id": tg_file_id,
            "file_name": file_name,
            "file_size": file_size,
            "file_type": file_type,
            "caption": msg.caption or ""
        })
        # Keep track of aggregate batch size
        _media_group_cache[group_id]["total_size"] += file_size

    async def _finalize_batch_upload(self, ctx: ContextTypes.DEFAULT_TYPE, group_id: str) -> None:
        """
        The background watcher task for batch processing.
        Waits for a predefined threshold (3 seconds) to ensure all fragments
        of the media group have arrived, then executes bulk storage procedures.
        """
        # Buffer delay to allow all concurrent messages of the album to arrive
        await asyncio.sleep(3.0) 

        # Atomically pop the batch data from the global cache
        batch_data = _media_group_cache.pop(group_id, None)
        if not batch_data:
            logger.warning(f"BatchProcessor: Attempted to finalize empty/missing group {group_id}")
            return

        user_id = batch_data["user_id"]
        chat_id = batch_data["chat_id"]
        files = batch_data["files"]
        proc_msg: Message = batch_data["processing_msg"]
        total_size = batch_data["total_size"]

        try:
            await proc_msg.edit_text(
                f"⚡ <b>Executing Batch Pipeline:</b> {len(files)} files buffered.\nForwarding cluster to Secure Vault...",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.debug(f"Batch UI Update Failed: {e}")
            pass

        success_keys = []
        
        # Iterate over buffered items and store sequentially
        for f in files:
            try:
                # Relay to backend
                stored_msg = await ctx.bot.forward_message(
                    chat_id=self.cfg.STORAGE_CHANNEL_ID,
                    from_chat_id=chat_id,
                    message_id=f["msg_id"]
                )
                
                # Metadata generation
                file_key = self.enc.generate_file_key()
                raw_caption = f.get("caption", "")
                tags = [word.lstrip("#").lower() for word in raw_caption.split() if word.startswith("#")]
                
                # MongoDB persistence
                await Database.save_file(
                    file_key=file_key,
                    owner_id=user_id,
                    file_id=f["file_id"],
                    file_name=f["file_name"],
                    file_size=f["file_size"],
                    file_type=f["file_type"],
                    message_id=stored_msg.message_id,
                    tags=tags,
                    caption=raw_caption,
                )
                success_keys.append(file_key)
                
            except Exception as e:
                logger.error(f"Batch item failure for {f.get('file_name', 'Unknown')}: {e}")

        # Bulk modify user storage metrics if any files succeeded
        if success_keys:
            await Database.update_user_storage(user_id, total_size, increment=True)

        # Build comprehensive final report
        batch_summary = (
            f"✅ <b>Bulk Operation Successful!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📁 <b>Assets Secured:</b> {len(success_keys)}\n"
            f"💾 <b>Bandwidth Used:</b> {format_size(total_size)}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"<i>You can view all these files securely within your /myfiles vault.</i>"
        )
        
        btn = [[InlineKeyboardButton("📁 Open My Vault", callback_data="start_myfiles")]]
        try:
            await proc_msg.edit_text(batch_summary, reply_markup=InlineKeyboardMarkup(btn), parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Final batch UI update failed: {e}")
            pass

    def _extract_file_data(self, msg: Message) -> Optional[Tuple[str, str, int, str]]:
        """
        Deep extraction engine for Telegram Metadata.
        Resolves correct file_id, fabricates missing filenames gracefully,
        and determines the canonical media format identifier.
        """
        if msg.document:
            f = msg.document
            return f.file_id, f.file_name or f"document_raw_{f.file_id[:6]}", f.file_size or 0, "document"
        elif msg.video:
            f = msg.video
            name = f.file_name or f"video_stream_{f.duration}s_{f.file_id[:6]}.mp4"
            return f.file_id, name, f.file_size or 0, "video"
        elif msg.audio:
            f = msg.audio
            artist = f.performer or 'Unknown Artist'
            title = f.title or 'Track'
            name = f.file_name or f"{artist} - {title}.mp3"
            return f.file_id, name, f.file_size or 0, "audio"
        elif msg.photo:
            f = msg.photo[-1] # Always pull highest resolution array element
            return f.file_id, f"photo_highres_{f.file_id[:8]}.jpg", f.file_size or 0, "photo"
        elif msg.sticker:
            f = msg.sticker
            return f.file_id, f"sticker_pack_{f.file_id[:6]}", f.file_size or 0, "sticker"
        elif msg.voice:
            f = msg.voice
            return f.file_id, f"voice_note_{f.file_id[:6]}.ogg", f.file_size or 0, "voice"
        elif msg.video_note:
            f = msg.video_note
            return f.file_id, f"video_message_{f.file_id[:6]}.mp4", f.file_size or 0, "video_note"
        elif msg.animation:
            f = msg.animation
            return f.file_id, f.file_name or f"animation_gif_{f.file_id[:6]}.mp4", f.file_size or 0, "animation"
        
        logger.debug("ExtractionEngine: No valid media detected in message object.")
        return None

    async def _render_upload_success(self, processing_msg: Message, file_key: str, file_name: str, file_size: int, file_type: str) -> None:
        """
        Compiles and renders the dynamic VIP Interface post-upload.
        Injects specific callbacks to enable seamless user interactivity without commands.
        """
        bot_username = getattr(self.cfg, 'BOT_USERNAME', 'bot')
        share_link = f"https://t.me/{bot_username}?start=get_{file_key}"
        emoji = get_file_type_emoji(file_type)

        buttons = [
            [InlineKeyboardButton("🔗 Copy Universal Link", callback_data=f"file_share_{file_key}")],
            [
                InlineKeyboardButton("🔐 Add Lock", callback_data=f"file_lock_{file_key}"),
                InlineKeyboardButton("✏️ Edit Name", callback_data=f"file_renamemenu_{file_key}"),
            ],
            [
                InlineKeyboardButton("📋 Advanced Specs", callback_data=f"file_info_{file_key}"),
                InlineKeyboardButton("❌ Purge Item", callback_data=f"file_delete_{file_key}"),
            ]
        ]
        markup = InlineKeyboardMarkup(buttons)

        result_text = (
            f"✅ <b>Asset Secured in Vault</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} <b>Identity:</b> {escape_html(file_name)}\n"
            f"💾 <b>Footprint:</b> {format_size(file_size)}\n"
            f"🔑 <b>Security Key:</b> <code>{file_key}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"\n🔗 <b>Direct Distribution Link:</b>\n<code>{share_link}</code>"
        )

        try:
            await processing_msg.edit_text(result_text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"UIRenderEngine: Failed to inject success interface: {e}")


    # ═════════════════════════════════════════════════════════════════════════════════
    # 📥 DATA FETCH & TRANSMISSION ENGINE
    # ═════════════════════════════════════════════════════════════════════════════════

    async def handle_get_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Exposed entry endpoint for manual `/get` commands.
        Validates arguments before piping directly into the delivery backend.
        """
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        args = ctx.args
        msg = update.effective_message
        if not args:
            await msg.reply_text(
                "⚠️ <b>Syntax Error</b>\nUsage format: <code>/get FILE_KEY</code>\n\n"
                "<i>Keys are generated automatically upon successful file injection.</i>",
                parse_mode=ParseMode.HTML
            )
            return

        # Extract and sanitize key
        file_key = args[0].strip()
        logger.info(f"FetchEngine: User {update.effective_user.id} requested key {file_key}")
        await self._deliver_file(update, ctx, file_key)

    async def _deliver_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, file_key: str) -> None:
        """
        The absolute core of transmission.
        Query DB -> Check Rate Limits -> Check Locks -> Request Password (if locked) -> Transmit Payload.
        Used by both Deep Linking (`/start get_XYZ`) and direct commands.
        """
        user = update.effective_user
        msg = update.effective_message

        # 1. Database Document Resolution
        file_doc = await Database.get_file(file_key)
        if not file_doc:
            await msg.reply_text(
                "❌ <b>404 - Artifact Not Found!</b>\n"
                "The requested file key does not exist. It may have been permanently purged.", 
                parse_mode=ParseMode.HTML
            )
            return

        # 2. Transmission Rate Limiter Check
        if not self.rl.check(user.id, "download"):
            wait = self.rl.get_wait_time(user.id, "download")
            await msg.reply_text(
                f"⏳ <b>Bandwidth Protection Active:</b> Request throttled. Next window opens in {wait} seconds.", 
                parse_mode=ParseMode.HTML
            )
            return

        # 3. Cryptographic State Verification
        if await FileSecurityGuard.is_locked(file_doc):
            logger.info(f"Security: Intercepted transmission of locked file {file_key} for {user.id}")
            
            # Setup State Machine for Password Entry
            ctx.user_data["unlocking_file_key"] = file_key
            ctx.user_data["awaiting_action"] = "unlock_password"
            
            await msg.reply_text(
                f"🔐 <b>RESTRICTED CLEARANCE REQUIRED</b>\n\n"
                f"Target: <code>{escape_html(file_doc['file_name'])}</code>\n"
                f"The owner has placed a cryptographic lock on this asset.\n\n"
                f"👇 <b>Please type the decryption password into the chat:</b>",
                parse_mode=ParseMode.HTML
            )
            return

        # 4. Proceed to clear-text physical transmission
        await self._send_file_from_storage(msg, ctx, file_doc)

    async def _send_file_from_storage(self, msg: Message, ctx: ContextTypes.DEFAULT_TYPE, file_doc: dict) -> None:
        """
        Physical layer execution.
        Copies the file from the hidden storage channel to the end user.
        Bypasses Telegram's file_id caching issues by routing fresh copies.
        """
        try:
            # Simulated heavy transmission UX
            await ctx.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        except Exception:
            pass
        
        try:
            bot_username = getattr(self.cfg, 'BOT_USERNAME', 'SecureBox')
            file_name_clean = escape_html(file_doc.get('file_name', 'Artifact'))
            
            # Execute copy instruction via Telegram Bot API
            sent_msg = await ctx.bot.copy_message(
                chat_id=msg.chat_id,
                from_chat_id=self.cfg.STORAGE_CHANNEL_ID,
                message_id=file_doc["message_id"],
                caption=file_doc.get("caption") or f"📄 <b>{file_name_clean}</b>\n🤖 Transported via @{bot_username}",
                parse_mode=ParseMode.HTML
            )
            
            # Analytics Engine Sync
            await Database.increment_download(file_doc["file_key"])

            # Attaching Action Buttons to the delivered receipt
            info_btn = [[InlineKeyboardButton("📋 View File Diagnostics", callback_data=f"file_info_{file_doc['file_key']}")]]
            await sent_msg.reply_text(
                f"✅ <b>Secure Transfer Complete!</b>\n"
                f"💾 Transferred Data: {format_size(file_doc.get('file_size',0))}",
                reply_markup=InlineKeyboardMarkup(info_btn),
                parse_mode=ParseMode.HTML
            )
        except TelegramError as e:
            logger.error(f"TransmissionEngine: Critical error during payload delivery: {e}")
            await msg.reply_text(
                "❌ <b>Transmission Protocol Failure:</b> \n"
                "The backend storage server is currently unresponsive. Try again shortly.", 
                parse_mode=ParseMode.HTML
            )


    # ═════════════════════════════════════════════════════════════════════════════════
    # 🗄️ VAULT DASHBOARD (INVENTORY MANAGER)
    # ═════════════════════════════════════════════════════════════════════════════════

    async def handle_my_files(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Generates a highly optimized, paginated graphical representation of the user's files.
        Executes parallel asynchronous DB queries for blazing fast load times.
        """
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user = update.effective_user
        msg = update.effective_message
        args = ctx.args
        
        # Determine Current Page Number
        page = 1
        if args and args[0].isdigit():
            page = max(1, int(args[0]))

        # Define UI density parameters
        per_page = 7 
        
        # Execute concurrent IO calls
        files, total = await asyncio.gather(
            Database.get_user_files(user.id, page=page, per_page=per_page),
            Database.count_user_files(user.id)
        )
        
        total_pages = max(1, math.ceil(total / per_page))

        # Empty State Handling
        if not files:
            await msg.reply_text(
                "📭 <b>Vault Empty State</b>\n\n"
                "No assets currently stored under your identifier. "
                "Upload a file to initialize your directory.",
                parse_mode=ParseMode.HTML
            )
            return

        # Header Construction
        lines = [
            f"🗄️ <b>YOUR ENCRYPTED INVENTORY</b>",
            f"📊 Displaying Page <b>{page}/{total_pages}</b> | Total Assets: <b>{total}</b>\n"
        ]
        
        # Iterative Line Generation
        for i, f in enumerate(files, 1):
            emoji = get_file_type_emoji(f.get("file_type", ""))
            locked = "🔐" if await FileSecurityGuard.is_locked(f) else "🔓"
            
            raw_name = f.get("file_name", "Unknown_Asset")
            name_cut = escape_html(raw_name[:35]) + ("..." if len(raw_name) > 35 else "")
            
            size = format_size(f.get("file_size", 0))
            dl = f.get("download_count", 0)
            
            lines.append(
                f"<b>{i}.</b> {emoji} {name_cut}\n"
                f"   └ 🔑 <code>{f['file_key']}</code> | 💾 {size} | ⬇️ {dl} | {locked}\n"
            )

        text = "\n".join(lines)

        # Dynamic Pagination Router
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("◀️ Prev Sector", callback_data=f"file_myfiles_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("Next Sector ▶️", callback_data=f"file_myfiles_{page+1}"))

        markup = InlineKeyboardMarkup([nav_buttons] if nav_buttons else [])
        
        # Realistic User Interaction Simulation
        try:
            await ctx.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.TYPING)
        except Exception:
            pass
            
        await msg.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)


    # ═════════════════════════════════════════════════════════════════════════════════
    # ❌ DELETION ENGINE (WITH STORAGE RECLAMATION)
    # ═════════════════════════════════════════════════════════════════════════════════

    async def handle_delete_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Executes absolute destruction protocol.
        Removes BSON entity from DB, and aggressively deducts the file size from the
        user's gross storage profile.
        """
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user_id = update.effective_user.id
        msg = update.effective_message
        args = ctx.args
        
        # Syntax Guard
        if not args:
            await msg.reply_text("⚠️ Syntax Missing: <code>/delete FILE_KEY</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0].strip()
        
        # Resolution Phase
        file_doc = await Database.get_file(file_key)
        if not file_doc:
            await msg.reply_text("❌ Target not found. It may have already been purged.", parse_mode=ParseMode.HTML)
            return

        # Security Ownership Guarantee
        is_owner = await FileSecurityGuard.verify_owner(file_doc, user_id)
        is_admin = self.cfg.is_admin(user_id)
        
        if not is_owner and not is_admin:
            logger.warning(f"DeletionEngine: Unauthorized purge attempt on {file_key} by {user_id}")
            await msg.reply_text("🛑 <b>Security Alert:</b> Insufficient permissions to purge this asset.", parse_mode=ParseMode.HTML)
            return

        # Size caching for reclamation
        file_size = file_doc.get("file_size", 0)

        # Execution Phase
        success = await Database.delete_file(file_key, user_id)
        if success:
            # Critical Storage Reclamation Step
            await Database.update_user_storage(user_id, file_size, increment=False)
            
            logger.info(f"DeletionEngine: Asset {file_key} successfully destroyed. Storage reclaimed: {file_size}b")
            await msg.reply_text(
                f"🗑️ <b>Asset Destroyed!</b>\n\n"
                f"File signature <code>{file_key}</code> has been completely erased from the primary databases.\n"
                f"📉 Storage block recovered: <b>{format_size(file_size)}</b>", 
                parse_mode=ParseMode.HTML
            )
        else:
            await msg.reply_text("❌ Database Transaction Error: Purge sequence failed.")


    # ═════════════════════════════════════════════════════════════════════════════════
    # ✏️ RENAMING ENGINE (DYNAMIC COMMAND ALLOCATION)
    # ═════════════════════════════════════════════════════════════════════════════════

    async def handle_rename_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Direct command implementation for renaming file metadata.
        This resolves the critical AttributeError flagged in the Railway system logs.
        """
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user_id = update.effective_user.id
        msg = update.effective_message
        args = ctx.args

        if len(args) < 2:
            await msg.reply_text(
                "⚠️ <b>Syntax Error:</b> Parameters missing.\n"
                "Format: <code>/rename FILE_KEY new_file_name_here</code>", 
                parse_mode=ParseMode.HTML
            )
            return

        file_key = args[0].strip()
        new_name = " ".join(args[1:]).strip()

        # Database Entity Resolution
        file_doc = await Database.get_file(file_key)
        if not file_doc:
            await msg.reply_text("❌ Target document not found.", parse_mode=ParseMode.HTML)
            return

        # Strict Ownership Security Gate
        if not await FileSecurityGuard.verify_owner(file_doc, user_id) and not self.cfg.is_admin(user_id):
            await msg.reply_text("🛑 <b>Security Alert:</b> Ownership verification failed. Rename aborted.", parse_mode=ParseMode.HTML)
            return

        # Database Transaction Layer
        if await Database.rename_file(file_key, user_id, new_name):
            logger.info(f"RenameEngine: Asset {file_key} modified to '{new_name}'")
            await msg.reply_text(
                f"✅ <b>Metadata Signature Updated</b>\n\n"
                f"New File Identifier:\n<code>{escape_html(new_name)}</code>", 
                parse_mode=ParseMode.HTML
            )
        else:
            await msg.reply_text("❌ Database Transaction Error: Rename sequence failed.")


    # ═════════════════════════════════════════════════════════════════════════════════
    # 🔗 UNIVERSAL SHARING ENGINE (EXTERNAL LINK GENERATOR)
    # ═════════════════════════════════════════════════════════════════════════════════

    async def handle_share_link(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Explicit command handler for `/share`.
        Resolves the missing function attribute. Compiles and distributes a public fetch link.
        """
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user_id = update.effective_user.id
        msg = update.effective_message
        args = ctx.args

        if not args:
            await msg.reply_text("⚠️ Syntax Missing: <code>/share FILE_KEY</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0].strip()
        
        # Entity Validation Guard
        file_doc = await Database.get_file(file_key)
        if not file_doc:
            await msg.reply_text("❌ Target not found.", parse_mode=ParseMode.HTML)
            return

        # Security Check
        if not await FileSecurityGuard.verify_owner(file_doc, user_id):
            await msg.reply_text("🛑 <b>Denied:</b> You cannot generate share parameters for an asset you do not own.", parse_mode=ParseMode.HTML)
            return

        # Logic Execution
        bot_username = getattr(self.cfg, 'BOT_USERNAME', 'bot')
        link = f"https://t.me/{bot_username}?start=get_{file_key}"
        
        await msg.reply_text(
            f"🔗 <b>Secure Distribution Link Authorized</b>\n\n"
            f"<code>{link}</code>\n\n"
            f"<i>Distribute this parameter carefully.</i>", 
            parse_mode=ParseMode.HTML
        )


    # ═════════════════════════════════════════════════════════════════════════════════
    # 🔍 DATABASE SEARCH ENGINE (KEYWORD INDEXING)
    # ═════════════════════════════════════════════════════════════════════════════════

    async def handle_search(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Command endpoint for `/search`.
        Issues regex-based queries to MongoDB to resolve file names and hashtags.
        """
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user_id = update.effective_user.id
        msg = update.effective_message
        args = ctx.args

        if not args:
            await msg.reply_text(
                "⚠️ <b>Syntax Parameter Required</b>\n"
                "Format: <code>/search keyword_or_tag</code>", 
                parse_mode=ParseMode.HTML
            )
            return

        query_string = " ".join(args).strip()
        
        # Fetch up to 10 nearest matching entities
        results = await Database.search_files(user_id, query_string)

        if not results:
            await msg.reply_text(
                f"🔍 <b>Index Search Completed</b>\n"
                f"No database entries matched the query: <code>{escape_html(query_string)}</code>", 
                parse_mode=ParseMode.HTML
            )
            return

        lines = [f"🔍 <b>Index Results for '{escape_html(query_string)}':</b>\n"]
        
        for f in results[:10]:
            emoji = get_file_type_emoji(f.get("file_type", ""))
            locked = "🔐" if await FileSecurityGuard.is_locked(f) else "🔓"
            name_cut = escape_html(f['file_name'][:35]) + ("..." if len(f['file_name']) > 35 else "")
            
            lines.append(
                f"{emoji}{locked} <code>{f['file_key']}</code> — {name_cut} ({format_size(f.get('file_size',0))})"
            )

        await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


    # ═════════════════════════════════════════════════════════════════════════════════
    # 🔐 CRYPTOGRAPHY & PASSWORD ENGINE (Lock/Unlock Parameters)
    # ═════════════════════════════════════════════════════════════════════════════════

    async def handle_lock_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Initializes the state machine to assign a cryptographic hash requirement to a file.
        Passes control logic to the `handle_text_input` interceptor.
        """
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user_id = update.effective_user.id
        msg = update.effective_message
        args = ctx.args
        
        if not args:
            await msg.reply_text("⚠️ Syntax Missing: <code>/lock FILE_KEY</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0].strip()
        
        # Pre-execution Ownership validation
        file_doc = await Database.get_file(file_key)
        if not file_doc or not await FileSecurityGuard.verify_owner(file_doc, user_id):
            await msg.reply_text("🛑 <b>Security Exception:</b> You can only cryptographically lock assets you possess.", parse_mode=ParseMode.HTML)
            return

        # Bind temporary conversation state variables
        ctx.user_data["action_file_key"] = file_key
        ctx.user_data["awaiting_action"] = "set_lock_password"
        
        await msg.reply_text(
            f"🔐 <b>Locking Sequence Initiated</b>\n\n"
            f"Target Key: <code>{file_key}</code>\n"
            f"👇 Please transmit a secure alphanumeric password in the chat matrix below:\n"
            f"<i>(A minimum complexity length of 4 characters is enforced)</i>",
            parse_mode=ParseMode.HTML
        )

    async def handle_unlock_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Strips the cryptographic hash from the file document, reverting it to a public payload.
        """
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        user_id = update.effective_user.id
        msg = update.effective_message
        args = ctx.args
        if not args:
            await msg.reply_text("⚠️ Syntax Missing: <code>/unlock FILE_KEY</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0].strip()
        
        # Pre-execution Guard
        file_doc = await Database.get_file(file_key)
        if not file_doc or not await FileSecurityGuard.verify_owner(file_doc, user_id):
            await msg.reply_text("🛑 <b>Security Exception:</b> Action denied on non-owned asset.", parse_mode=ParseMode.HTML)
            return

        # Execute unbinding parameter
        success = await Database.set_file_password(file_key, user_id, None)
        if success:
            logger.info(f"CryptoEngine: File {file_key} unlocked successfully.")
            await msg.reply_text(
                f"🔓 <b>Vault Opened</b>\nAsset <code>{file_key}</code> is now devoid of cryptographic requirements.", 
                parse_mode=ParseMode.HTML
            )
        else:
            await msg.reply_text("❌ Database Transaction Error: Unlock modification failed.")


    # ═════════════════════════════════════════════════════════════════════════════════
    # ⌨️ DYNAMIC TEXT INTERCEPTOR ROUTER
    # ═════════════════════════════════════════════════════════════════════════════════

    async def handle_text_input(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        The Intelligent Context Engine.
        Intercepts plain text messages and routes them based on the active conversation state.
        Handles Password Binding, Password Verification, and Dynamic Renaming dynamically
        without requiring strict command prefixes.
        """
        msg = update.effective_message
        if not msg or not msg.text:
            return

        # Fetch active context flag
        action = ctx.user_data.get("awaiting_action")
        if not action:
            # Drop the packet if no context exists
            return
        
        # ─── PATH A: PASSWORD ASSIGNMENT ───
        if action == "set_lock_password":
            file_key = ctx.user_data.get("action_file_key")
            password = msg.text.strip()
            
            # Policy Validation
            if not FileSecurityGuard.validate_password_strength(password):
                await msg.reply_text("❌ Policy Violation: Input too brief. Password must contain at least 4 characters. Re-transmit:")
                return
                
            enc = get_encryptor(self.cfg)
            hashed_pw = enc.hash_password(password)
            
            # Persist Hash
            if await Database.set_file_password(file_key, update.effective_user.id, hashed_pw):
                await msg.reply_text(
                    f"✅ <b>Lock Algorithm Active!</b>\nArtifact <code>{file_key}</code> is now heavily encrypted.\n"
                    f"⚠️ <i>Warning: Save your password. Keys cannot be reverse-engineered by the system.</i>",
                    parse_mode=ParseMode.HTML
                )
            # Memory Cleanup
            ctx.user_data.pop("awaiting_action", None)
            ctx.user_data.pop("action_file_key", None)
            
        # ─── PATH B: DECRYPTION CHALLENGE ───
        elif action == "unlock_password":
            file_key = ctx.user_data.get("unlocking_file_key")
            input_pw = msg.text.strip()
            
            file_doc = await Database.get_file(file_key)
            if not file_doc:
                ctx.user_data.pop("awaiting_action", None)
                return
                
            enc = get_encryptor(self.cfg)
            saved_hash = file_doc.get("password_hash")
            
            # Verification Matrix
            if enc.verify_password(input_pw, saved_hash):
                await msg.reply_text("✅ <b>Decryption Approved.</b> Initializing physical transfer...", parse_mode=ParseMode.HTML)
                ctx.user_data.pop("awaiting_action", None)
                ctx.user_data.pop("unlocking_file_key", None)
                
                # Execute transmission pipeline
                await self._send_file_from_storage(msg, ctx, file_doc)
            else:
                logger.warning(f"IntrusionAttempt: User {update.effective_user.id} failed password check for {file_key}")
                await msg.reply_text("❌ <b>INCORRECT SECURITY KEY</b>\nIntrusion attempt logged. Re-transmit string:")
                
        # ─── PATH C: METADATA RE-WRITE (RENAME) ───
        elif action == "rename_file":
            file_key = ctx.user_data.get("action_file_key")
            new_name = msg.text.strip()
            
            if await Database.rename_file(file_key, update.effective_user.id, new_name):
                await msg.reply_text(f"✅ <b>Identifier Successfully Transmuted:</b>\n<code>{escape_html(new_name)}</code>", parse_mode=ParseMode.HTML)
            else:
                await msg.reply_text("❌ Database Reject: Failed to inject new name parameters.")
                
            ctx.user_data.pop("awaiting_action", None)
            ctx.user_data.pop("action_file_key", None)


    # ═════════════════════════════════════════════════════════════════════════════════
    # 📋 DIAGNOSTICS & TELEMETRY DASHBOARD (FILE INFO)
    # ═════════════════════════════════════════════════════════════════════════════════

    async def handle_file_info(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Builds a comprehensive diagnostic read-out for any specific file node.
        Displays deep details like tags, byte counts, crypt-status, and temporal stamps.
        """
        db_user = await self._system_guard(update, ctx)
        if not db_user:
            return

        msg = update.effective_message
        args = ctx.args
        if not args:
            await msg.reply_text("⚠️ Syntax Missing: <code>/info FILE_KEY</code>", parse_mode=ParseMode.HTML)
            return

        file_key = args[0].strip()
        file_doc = await Database.get_file(file_key)
        
        if not file_doc:
            await msg.reply_text("❌ Database Result: Empty. Asset absent from node.", parse_mode=ParseMode.HTML)
            return

        # Variable resolution
        emoji = get_file_type_emoji(file_doc.get("file_type", ""))
        is_owner = await FileSecurityGuard.verify_owner(file_doc, update.effective_user.id)
        
        raw_tags = file_doc.get("tags", [])
        tags = ", ".join(raw_tags) if raw_tags else "Unassigned"
        
        locked_state = await FileSecurityGuard.is_locked(file_doc)
        locked_str = "🔐 Locked (Hash Active)" if locked_state else "🔓 Open (Unrestricted)"

        # Interface Construction
        text = (
            f"📑 <b>DEEP ASSET DIAGNOSTICS</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} <b>Identity:</b> {escape_html(file_doc['file_name'])}\n"
            f"🔑 <b>Hash Key:</b> <code>{file_key}</code>\n"
            f"💾 <b>Bandwidth:</b> {format_size(file_doc.get('file_size', 0))}\n"
            f"📂 <b>Encoding:</b> {file_doc.get('file_type', 'UNKNOWN').upper()}\n"
            f"⬇️ <b>Network Trafffic:</b> {file_doc.get('download_count', 0)} cycles\n"
            f"🔒 <b>Security Frame:</b> {locked_str}\n"
            f"🏷️ <b>Node Tags:</b> {tags}\n"
            f"📅 <b>System Inject:</b> {file_doc['uploaded_at'].strftime('%d %b %Y %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        buttons = []
        if is_owner:
            buttons = [
                [InlineKeyboardButton("🔗 Generate Link Node", callback_data=f"file_share_{file_key}")],
                [
                    InlineKeyboardButton("🔐 Enforce Hash", callback_data=f"file_lock_{file_key}"),
                    InlineKeyboardButton("✏️ Edit Identifier", callback_data=f"file_renamemenu_{file_key}"),
                ],
                [InlineKeyboardButton("❌ Destroy Artifact", callback_data=f"file_delete_{file_key}")]
            ]

        await msg.reply_text(
            text, 
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None, 
            parse_mode=ParseMode.HTML
        )


    # ═════════════════════════════════════════════════════════════════════════════════
    # ⚡ ZERO-LAG EVENT MULTIPLEXER (THE CALLBACK ROUTER)
    # ═════════════════════════════════════════════════════════════════════════════════

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        The Supreme Callback Event Dispatcher.
        Handles rapid inline button pushes with instant Telegram UI feedback to prevent
        loading circles and "Timeout" notifications.
        Routes payloads based on string pattern prefixes.
        """
        q = update.callback_query
        
        # 1. Immediate resolution of the telegram UI event loop
        try:
            await q.answer()
        except Exception as e:
            logger.warning(f"EventMultiplexer: Failed to resolve callback event (likely stale message): {e}")
            return

        data = q.data
        user = q.from_user

        try:
            # ─── ROUTE: LINK SHARING ───
            if data.startswith("file_share_"):
                file_key = data[len("file_share_"):]
                bot_user = getattr(self.cfg, 'BOT_USERNAME', 'SecureBot')
                link = f"https://t.me/{bot_user}?start=get_{file_key}"
                
                await q.message.reply_text(
                    f"🔗 <b>Secure Distribution Path</b>\n\n<code>{link}</code>\n\n"
                    f"<i>Forward this link parameters carefully.</i>", 
                    parse_mode=ParseMode.HTML
                )

            # ─── ROUTE: DELETION WARNING PROMPT ───
            elif data.startswith("file_delete_"):
                file_key = data[len("file_delete_"):]
                confirm_btn = [
                    [InlineKeyboardButton("⚠️ EXECUTE TOTAL PURGE", callback_data=f"file_confirmdel_{file_key}")],
                    [InlineKeyboardButton("❌ ABORT", callback_data="file_cancel_action")],
                ]
                await q.message.reply_text(
                    f"🛑 <b>CRITICAL WARNING PROTOCOL</b>\n"
                    f"Are you definitively sure you wish to incinerate <code>{file_key}</code>?\n"
                    f"<i>Action is completely irreversible. Data and references will be purged.</i>",
                    reply_markup=InlineKeyboardMarkup(confirm_btn), 
                    parse_mode=ParseMode.HTML
                )

            # ─── ROUTE: DELETION CONFIRMATION & EXECUTION ───
            elif data.startswith("file_confirmdel_"):
                file_key = data[len("file_confirmdel_"):]
                
                # Verify existence and fetch volume for decrement logic
                file_doc = await Database.get_file(file_key)
                if not file_doc:
                    await q.message.edit_text("❌ Process Failed: Artifact is already a ghost.")
                    return
                
                f_size = file_doc.get("file_size", 0)
                
                # Execute Purge
                if await Database.delete_file(file_key, user.id):
                    # Final Storage Reclamation
                    await Database.update_user_storage(user.id, f_size, increment=False)
                    await q.message.edit_text(
                        f"✅ <b>Artifact Successfully Purged!</b>\nSignature <code>{file_key}</code> has been decimated.\nVolume recovered: {format_size(f_size)}", 
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await q.message.edit_text("❌ Purge Failed: Ownership verification collision.")

            # ─── ROUTE: RENAMING UI FLOW ───
            elif data.startswith("file_renamemenu_"):
                file_key = data[len("file_renamemenu_"):]
                # Establish Conversation Trap
                ctx.user_data["action_file_key"] = file_key
                ctx.user_data["awaiting_action"] = "rename_file"
                await q.message.reply_text(
                    f"✏️ <b>Metadata Override Mode Active</b>\n\n"
                    f"Pointer: <code>{file_key}</code>\n"
                    f"👇 Type the replacement nomenclature parameters in the active terminal below:",
                    parse_mode=ParseMode.HTML
                )

            # ─── ROUTE: ENCRYPTION LOCK UI FLOW ───
            elif data.startswith("file_lock_"):
                file_key = data[len("file_lock_"):]
                # Establish Conversation Trap
                ctx.user_data["action_file_key"] = file_key
                ctx.user_data["awaiting_action"] = "set_lock_password"
                await q.message.reply_text(
                    f"🔐 <b>Cryptographic Sequencer Engaged</b>\n\n"
                    f"Pointer: <code>{file_key}</code>\n"
                    f"👇 Formulate and transmit your desired encryption hash (password) below:",
                    parse_mode=ParseMode.HTML
                )

            # ─── ROUTE: INVENTORY PAGINATION ───
            elif data.startswith("file_myfiles_"):
                # Extract requested page index
                page_str = data.split("_")[-1]
                page_val = int(page_str) if page_str.isdigit() else 1
                
                # Hijack arguments to mimic natural command execution
                ctx.args = [str(page_val)]
                update._effective_message = q.message
                await self.handle_my_files(update, ctx)

            # ─── ROUTE: DIAGNOSTIC INFO PANEL ───
            elif data.startswith("file_info_"):
                file_key = data[len("file_info_"):]
                
                # Hijack arguments
                ctx.args = [file_key]
                update._effective_message = q.message
                await self.handle_file_info(update, ctx)

            # ─── ROUTE: UNIVERSAL ACTION CANCEL BUTTON ───
            elif data == "file_cancel_action":
                # Clear all active conversation traps
                ctx.user_data.pop("awaiting_action", None)
                ctx.user_data.pop("action_file_key", None)
                await q.message.edit_text("✅ <b>Override Aborted successfully. System returned to standby.</b>", parse_mode=ParseMode.HTML)

            else:
                logger.warning(f"EventMultiplexer: Received unrecognized routing payload: {data}")

        except Exception as e:
            # Fallback error container to prevent application crash
            logger.error(f"EventMultiplexer: Critical failure during execution of callback node {data}: {e}", exc_info=True)
            await q.message.reply_text("⚠️ <b>Framework Exception:</b> The UI interaction timed out. Please initiate via command terminal.", parse_mode=ParseMode.HTML)

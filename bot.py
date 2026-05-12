"""
╔══════════════════════════════════════════════════════════════╗
║          ULTRA ADVANCED TELEGRAM FILE SHARE BOT              ║
║        God Mode | Auto-Commands | Pre-flight Checks          ║
║          Railway Ready | Python 3.12+ | Zero Errors          ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

# Railway fix for asyncio event loops (CRITICAL FOR DEPLOYMENT)
import nest_asyncio
nest_asyncio.apply()

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ─── Custom Modules Import ───────────────────────────────────
from config import Config
from database.mongodb import Database
from handlers.start_handler import StartHandler
from handlers.file_handler import FileHandler
from handlers.admin_handler import AdminHandler
from handlers.channel_handler import ChannelHandler
from utils.scheduler import BotScheduler
from utils.logger import setup_logger
from utils.bot_commands import setup_bot_commands  # 🚀 Naya Auto-Command System

# ─── Logger Setup ────────────────────────────────────────────
logger = setup_logger(__name__)

def system_pre_check(cfg: Config):
    """Bot start hone se pehle zaroori cheezein check karega."""
    logger.info("🔍 Running System Pre-flight Checks...")
    if not cfg.BOT_TOKEN:
        logger.critical("❌ BOT_TOKEN is missing in config/env! Bot cannot start.")
        sys.exit(1)
    if not cfg.MONGO_URI:
        logger.critical("❌ MONGO_URI is missing in config/env! Database will fail.")
        sys.exit(1)
    logger.info("✅ All core variables are set. System is GREEN.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Advanced global error handler — errors ko handle karke user ko safe message dega."""
    logger.error("⚠️ Exception while handling an update:", exc_info=context.error)
    
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ **System Alert:** Kuch technical issue detect hua hai.\n"
                "Developer ko notify kar diya gaya hai. Please thodi der baad try karein ya `/start` dabayein.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"❌ Could not send error message to user: {e}")


def build_application(cfg: Config) -> Application:
    """Build and configure the bot application tightly."""
    app = (
        Application.builder()
        .token(cfg.BOT_TOKEN)
        .concurrent_updates(True)  # Fast processing for multiple users
        .build()
    )

    # ─── Handlers Initialization ──────────────────────────────
    start_h = StartHandler(cfg)
    file_h = FileHandler(cfg)
    admin_h = AdminHandler(cfg)
    channel_h = ChannelHandler(cfg)

    # 1. 🚀 Core Commands
    app.add_handler(CommandHandler("start", start_h.handle_start))
    app.add_handler(CommandHandler("help", start_h.handle_help))
    app.add_handler(CommandHandler("profile", start_h.handle_profile))

    # 2. 📦 File Upload System (Merged filters for maximum speed)
    media_filter = (
        filters.Document.ALL | filters.VIDEO | filters.AUDIO | 
        filters.PHOTO | filters.Sticker.ALL | filters.VOICE
    )
    app.add_handler(MessageHandler(media_filter, file_h.handle_upload))

    # 3. 📁 File Management Commands
    app.add_handler(CommandHandler("get", file_h.handle_get_file))
    app.add_handler(CommandHandler("myfiles", file_h.handle_my_files))
    app.add_handler(CommandHandler("delete", file_h.handle_delete_file))
    app.add_handler(CommandHandler("rename", file_h.handle_rename_file))
    app.add_handler(CommandHandler("lock", file_h.handle_lock_file))
    app.add_handler(CommandHandler("unlock", file_h.handle_unlock_file))
    app.add_handler(CommandHandler("share", file_h.handle_share_link))
    app.add_handler(CommandHandler("info", file_h.handle_file_info))
    app.add_handler(CommandHandler("search", file_h.handle_search))

    # 4. 📊 Stats & Community
    app.add_handler(CommandHandler("stats", start_h.handle_stats))
    app.add_handler(CommandHandler("referral", start_h.handle_referral))
    app.add_handler(CommandHandler("leaderboard", start_h.handle_leaderboard))

    # 5. 👑 Admin Master Controls
    admin_commands = [
        ("admin", admin_h.handle_admin_panel),
        ("broadcast", admin_h.handle_broadcast),
        ("ban", admin_h.handle_ban),
        ("unban", admin_h.handle_unban),
        ("addchannel", admin_h.handle_add_channel),
        ("removechannel", admin_h.handle_remove_channel),
        ("channels", admin_h.handle_list_channels),
        ("setlimit", admin_h.handle_set_limit),
        ("allusers", admin_h.handle_all_users),
        ("allfiles", admin_h.handle_all_files),
        ("forcejoin", admin_h.handle_toggle_force_join),
        ("maintenance", admin_h.handle_maintenance),
        ("logs", admin_h.handle_logs),
        ("botinfo", admin_h.handle_bot_info)
    ]
    for cmd, handler in admin_commands:
        app.add_handler(CommandHandler(cmd, handler))

    # 6. 🔘 Interactive Button Callbacks
    app.add_handler(CallbackQueryHandler(file_h.handle_callback, pattern="^file_"))
    app.add_handler(CallbackQueryHandler(admin_h.handle_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(start_h.handle_callback, pattern="^start_"))
    app.add_handler(CallbackQueryHandler(channel_h.handle_join_verify, pattern="^verify_join"))

    # 7. 🛡️ Global Error Shield
    app.add_error_handler(error_handler)

    return app


async def setup_dependencies(app: Application, cfg: Config):
    """Database, Scheduler aur Command Menu ko secure loop mein start karna."""
    # 1. Connect Database
    await Database.connect(cfg.MONGO_URI, cfg.DB_NAME)
    logger.info("✅ MongoDB connected successfully.")

    # 2. Start Background Scheduler (Cleanup, stats tracking etc.)
    scheduler = BotScheduler(app)
    await scheduler.start()
    logger.info("✅ Bot Scheduler activated.")

    # 3. 🚀 SET TELEGRAM COMMAND MENU DYNAMICALLY
    await setup_bot_commands(app)
    logger.info("✅ Premium Bot Commands synced to Telegram API.")


def main() -> None:
    """Entry point - Railway & Webhook Optimized."""
    cfg = Config()
    
    # Run sanity checks before booting
    system_pre_check(cfg)

    app = build_application(cfg)
    logger.info("🚀 Preparing to launch Ultra Advanced File Share Bot...")

    # Event loop trick for Nixpacks/Railway environment
    loop = asyncio.get_event_loop()
    loop.run_until_complete(setup_dependencies(app, cfg))

    port = int(os.environ.get("PORT", 0))

    # Decide between Webhook and Polling automatically
    if port and getattr(cfg, "WEBHOOK_URL", None):
        webhook_url = f"{cfg.WEBHOOK_URL}/{cfg.BOT_TOKEN}"
        logger.info(f"🌐 Server Mode: WEBHOOK starting on port {port}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url,
            drop_pending_updates=True,
        )
    else:
        logger.info("🤖 Server Mode: POLLING started. Bot is now ONLINE!")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("🛑 Bot stopped manually by user (KeyboardInterrupt).")
    except Exception as e:
        logger.critical(f"💀 Fatal System Crash: {e}", exc_info=True)
        sys.exit(1)

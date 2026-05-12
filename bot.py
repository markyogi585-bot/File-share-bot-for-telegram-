"""
╔══════════════════════════════════════════════════════════════╗
║          ULTRA ADVANCED TELEGRAM FILE SHARE BOT              ║
║          Force Join + Encrypted Files + Admin Panel          ║
║          Railway Ready | Python 3.12+ | Zero Errors          ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

# Railway fix for asyncio event loops
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

from config import Config
from database.mongodb import Database
from handlers.start_handler import StartHandler
from handlers.file_handler import FileHandler
from handlers.admin_handler import AdminHandler
from handlers.channel_handler import ChannelHandler
from utils.scheduler import BotScheduler
from utils.logger import setup_logger

# ─── Logger Setup ────────────────────────────────────────────
logger = setup_logger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler — zero errors reach user."""
    logger.error("Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Kuch technical issue aa gaya. Please /start karo dobara."
            )
        except Exception:
            pass


def build_application() -> Application:
    """Build and configure the bot application."""
    cfg = Config()

    app = (
        Application.builder()
        .token(cfg.BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # ─── Handlers ────────────────────────────────────────────
    start_h = StartHandler(cfg)
    file_h = FileHandler(cfg)
    admin_h = AdminHandler(cfg)
    channel_h = ChannelHandler(cfg)

    # Start & Deep Link
    app.add_handler(CommandHandler("start", start_h.handle_start))

    # File upload handlers (all media types)
    app.add_handler(MessageHandler(filters.Document.ALL, file_h.handle_upload))
    app.add_handler(MessageHandler(filters.VIDEO, file_h.handle_upload))
    app.add_handler(MessageHandler(filters.AUDIO, file_h.handle_upload))
    app.add_handler(MessageHandler(filters.PHOTO, file_h.handle_upload))
    app.add_handler(MessageHandler(filters.Sticker.ALL, file_h.handle_upload))
    app.add_handler(MessageHandler(filters.VOICE, file_h.handle_upload))

    # File retrieval via link
    app.add_handler(CommandHandler("get", file_h.handle_get_file))
    app.add_handler(CommandHandler("myfiles", file_h.handle_my_files))
    app.add_handler(CommandHandler("delete", file_h.handle_delete_file))
    app.add_handler(CommandHandler("rename", file_h.handle_rename_file))
    app.add_handler(CommandHandler("lock", file_h.handle_lock_file))
    app.add_handler(CommandHandler("unlock", file_h.handle_unlock_file))
    app.add_handler(CommandHandler("share", file_h.handle_share_link))
    app.add_handler(CommandHandler("info", file_h.handle_file_info))
    app.add_handler(CommandHandler("search", file_h.handle_search))

    # User commands
    app.add_handler(CommandHandler("help", start_h.handle_help))
    app.add_handler(CommandHandler("profile", start_h.handle_profile))
    app.add_handler(CommandHandler("stats", start_h.handle_stats))
    app.add_handler(CommandHandler("referral", start_h.handle_referral))
    app.add_handler(CommandHandler("leaderboard", start_h.handle_leaderboard))

    # Admin commands
    app.add_handler(CommandHandler("admin", admin_h.handle_admin_panel))
    app.add_handler(CommandHandler("broadcast", admin_h.handle_broadcast))
    app.add_handler(CommandHandler("ban", admin_h.handle_ban))
    app.add_handler(CommandHandler("unban", admin_h.handle_unban))
    app.add_handler(CommandHandler("addchannel", admin_h.handle_add_channel))
    app.add_handler(CommandHandler("removechannel", admin_h.handle_remove_channel))
    app.add_handler(CommandHandler("channels", admin_h.handle_list_channels))
    app.add_handler(CommandHandler("setlimit", admin_h.handle_set_limit))
    app.add_handler(CommandHandler("allusers", admin_h.handle_all_users))
    app.add_handler(CommandHandler("allfiles", admin_h.handle_all_files))
    app.add_handler(CommandHandler("forcejoin", admin_h.handle_toggle_force_join))
    app.add_handler(CommandHandler("maintenance", admin_h.handle_maintenance))
    app.add_handler(CommandHandler("logs", admin_h.handle_logs))
    app.add_handler(CommandHandler("botinfo", admin_h.handle_bot_info))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(file_h.handle_callback, pattern="^file_"))
    app.add_handler(CallbackQueryHandler(admin_h.handle_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(start_h.handle_callback, pattern="^start_"))
    app.add_handler(CallbackQueryHandler(channel_h.handle_join_verify, pattern="^verify_join"))

    # Global error handler
    app.add_error_handler(error_handler)

    return app


async def setup_dependencies(app: Application):
    """Database aur scheduler setup karne ka alag function taaki loop clash na ho."""
    cfg = Config()
    await Database.connect(cfg.MONGO_URI, cfg.DB_NAME)
    logger.info("✅ MongoDB connected")

    scheduler = BotScheduler(app)
    await scheduler.start()
    logger.info("✅ Scheduler started")


def main() -> None:
    """Main function - Modified for zero loop errors on Railway."""
    app = build_application()
    logger.info("🚀 Bot starting up...")

    # Event loop banake dependencies setup karte hain bina application run kiye
    loop = asyncio.get_event_loop()
    loop.run_until_complete(setup_dependencies(app))

    # Railway webhook and polling logic
    cfg = Config()
    port = int(os.environ.get("PORT", 0))

    if port and getattr(cfg, "WEBHOOK_URL", None):
        webhook_url = f"{cfg.WEBHOOK_URL}/{cfg.BOT_TOKEN}"
        logger.info(f"🌐 Starting via Webhook on port {port}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url,
            drop_pending_updates=True,
        )
    else:
        logger.info("🤖 Starting via Polling")
        # Run polling blocks thread, avoids asyncio.run() clash
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

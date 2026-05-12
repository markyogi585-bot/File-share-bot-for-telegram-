"""
╔══════════════════════════════════════════════════════════════╗
║             ULTRA PREMIUM COMMAND MANAGEMENT SYSTEM          ║
║       Dynamic Scopes | Multi-Level Menu | Admin Exclusive    ║
╚══════════════════════════════════════════════════════════════╝
"""

import logging
from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import Application
from config import Config

# Logger setup taaki har activity track ho
logger = logging.getLogger(__name__)

async def setup_bot_commands(app: Application):
    """
    Bot commands ko automatically set karne ka advanced function.
    Isme 'Default Scope' sabke liye hai aur 'Chat Scope' Admin ke liye.
    """
    cfg = Config()
    
    # ─── 💎 USER COMMANDS (Visible to Everyone) ──────────────
    # Inhe ekdum clean aur attractive rakha hai
    user_commands = [
        BotCommand("start", "🚀 Start | Restart the Bot"),
        BotCommand("myfiles", "📁 My Files | Manage your uploads"),
        BotCommand("search", "🔍 Search | Find files globally"),
        BotCommand("share", "📤 Share | Get shareable link"),
        BotCommand("lock", "🔐 Lock | Add password to file"),
        BotCommand("unlock", "🔓 Unlock | Remove password"),
        BotCommand("profile", "👤 Profile | Account statistics"),
        BotCommand("leaderboard", "🏆 Top | See top uploaders"),
        BotCommand("help", "❓ Help | How to use the bot"),
    ]

    # ─── 👑 ADMIN/OWNER COMMANDS (Exclusive Access) ───────────
    # Ye commands normal users ko menu mein NAHI dikhengi
    admin_only_commands = [
        BotCommand("admin", "👑 ADMIN PANEL | Master Control"),
        BotCommand("broadcast", "📢 BROADCAST | Send message to all"),
        BotCommand("forcejoin", "🔒 FORCE JOIN | Setup channels"),
        BotCommand("stats", "📊 GLOBAL STATS | Bot health & data"),
        BotCommand("ban", "🚫 BAN | Blacklist a user"),
        BotCommand("unban", "✅ UNBAN | White-list a user"),
        BotCommand("maintenance", "🛠️ MODE | Toggle maintenance"),
        BotCommand("logs", "📄 LOGS | View system errors"),
        BotCommand("setlimit", "📤 LIMITS | Set upload/download limits"),
    ]

    # Dono ko mix karke Admin ki list banate hain
    full_admin_list = user_commands + admin_only_commands

    try:
        # 1. Sabse pehle default menu set karo (For all users)
        await app.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
        logger.info("💎 Global User Menu deployed successfully.")

        # 2. Ab specific Owners/Admins ke liye menu set karo
        # Agar config mein OWNER_ID list hai toh loop chalayenge
        owner_id = getattr(cfg, 'OWNER_ID', None)
        
        if owner_id:
            # Agar single ID hai toh usse list bana do
            owner_ids = [owner_id] if isinstance(owner_id, (int, str)) else owner_id
            
            for admin_id in owner_ids:
                try:
                    await app.bot.set_my_commands(
                        full_admin_list, 
                        scope=BotCommandScopeChat(chat_id=admin_id)
                    )
                    logger.info(f"👑 Admin Menu deployed for ID: {admin_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not set admin menu for {admin_id}: {e}")

        logger.info("✅ ALL COMMANDS SYNCED IN BEAST MODE!")

    except Exception as e:
        logger.error(f"❌ CRITICAL: Command menu sync failed: {e}")

